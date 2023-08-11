import base64
import uuid
import sys
from collections import OrderedDict
from datetime import datetime
from decimal import Decimal
from django import forms
from django.conf import settings
from django.forms import Form
from django.http import HttpRequest
from django.template.loader import get_template
from django.utils.crypto import get_random_string
from django.core.signing import Signer
from django.utils.translation import get_language, gettext_lazy as _, to_locale
from pretix.multidomain.urlreverse import build_absolute_uri
from pretix.base.models import Event
from django_countries.fields import Country
from pretix.base.forms.questions import guess_country
from pretix.base.models import InvoiceAddress, Order, OrderPayment
from pretix.base.payment import BasePaymentProvider
from pretix.helpers.countries import CachedCountries
from pretix.presale.views.cart import cart_session

MONETICOPAIEMENT_VERSION = "3.0"

def get_signed_uuid4(request):
    signer = Signer()
    uuid4_signed_bytes = signer.sign(
        request.session["payment_moneticopayment_uuid4"]
    ).encode("ascii")
    signed_uuid4 = uuid4_signed_bytes.hex().upper()
    return signed_uuid4


def check_signed_uuid4(signed_uuid4):
    signer = Signer()
    uuid4_signed_bytes = bytes.fromhex(signed_uuid4)
    uuid4_signed = uuid4_signed_bytes.decode("ascii")
    return signer.unsign(uuid4_signed)


def getNonce(request):
    if "_monetico_nonce" not in request.session:
        request.session["_monetico_nonce"] = get_random_string(32)
    return request.session["_monetico_nonce"]


class MoneticoPayment(BasePaymentProvider):
    identifier = "moneticopayment"
    verbose_name = _("Monetico Payment")
    abort_pending_allowed = True
    ia = InvoiceAddress()

    def __init__(self, event: Event):
        super().__init__(event)

    @property
    def test_mode_message(self):
        return _(
            "In test mode, you can just manually mark this order as paid in the backend after it has been "
            "created."
        )

    @property
    def settings_form_fields(self):
        fields = [
            (
                "monetico_key",
                forms.CharField(
                    label=_("Monetico key"),
                    max_length=40,
                    min_length=40,
                    help_text=_("This is your Monetico key"),
                    initial="12345678901234567890123456789012345678P0",
                ),
            ),
            (
                "monetico_ept_number",
                forms.CharField(
                    label=_("Monetico EPT number"),
                    max_length=8,
                    min_length=3,
                    initial="0000001",
                ),
            ),
            (
                "monetico_url_server",
                forms.CharField(
                    label=_("Monetico server"),
                    help_text=_("The base URL or the Monetico server"),
                    initial="https://p.monetico-services.com/test/",
                ),
            ),
            (
                "monetico_payment_url",
                forms.CharField(
                    label=_("Monetico payment URL"),
                    help_text=_("The final part of the Monetico URL"),
                    initial="paiement.cgi",
                ),
            ),
            (
                "monetico_company_code",
                forms.CharField(
                    label=_("Monetico company code"),
                    help_text=_("Your Monetico company code"),
                    max_length=20,
                    min_length=20,
                ),
            ),
        ]
        return OrderedDict(fields + list(super().settings_form_fields.items()))

    def payment_form_render(
        self, request: HttpRequest, total: Decimal, order: Order = None
    ) -> str:
        def get_invoice_address():
            if order and getattr(order, "invoice_address", None):
                request._checkout_flow_invoice_address = order.invoice_address
            if not hasattr(request, "_checkout_flow_invoice_address"):
                cs = cart_session(request)
                iapk = cs.get("invoice_address")
                if not iapk:
                    request._checkout_flow_invoice_address = InvoiceAddress()
                else:
                    try:
                        request._checkout_flow_invoice_address = (
                            InvoiceAddress.objects.get(pk=iapk, order__isnull=True)
                        )
                    except InvoiceAddress.DoesNotExist:
                        request._checkout_flow_invoice_address = InvoiceAddress()
            return request._checkout_flow_invoice_address

        self.ia = get_invoice_address()
        # print(cs, file=sys.stderr)
        # print(self.ia.name_parts, file=sys.stderr)
        form = self.payment_form(request)
        template = get_template(
            "pretixpresale/event/checkout_payment_form_default.html"
        )
        ctx = {"request": request, "form": form}
        return template.render(ctx)

    @property
    def payment_form_fields(self):
        print("MoneticoPayment.payment_form_fields", file=sys.stderr)
        print(CachedCountries(), file=sys.stderr)
        return OrderedDict(
            [
                (
                    "lastname",
                    forms.CharField(
                        label=_("Card Holder Last Name"),
                        required=True,
                        initial=self.ia.name_parts["given_name"]
                        if "given_name" in self.ia.name_parts
                        else None,
                    ),
                ),
                (
                    "firstname",
                    forms.CharField(
                        label=_("Card Holder First Name"),
                        required=True,
                        initial=self.ia.name_parts["family_name"]
                        if "family_name" in self.ia.name_parts
                        else None,
                    ),
                ),
                (
                    "line1",
                    forms.CharField(
                        label=_("Card Holder Street"),
                        required=True,
                        initial=self.ia.street or None,
                    ),
                ),
                (
                    "line2",
                    forms.CharField(
                        label=_("Card Holder Address Complement"),
                        required=False,
                    ),
                ),
                (
                    "postal_code",
                    forms.CharField(
                        label=_("Card Holder Postal Code"),
                        required=True,
                        initial=self.ia.zipcode or None,
                    ),
                ),
                (
                    "city",
                    forms.CharField(
                        label=_("Card Holder City"),
                        required=True,
                        initial=self.ia.city or None,
                    ),
                ),
                (
                    "country",
                    forms.ChoiceField(
                        label=_("Card Holder Country"),
                        required=True,
                        choices=CachedCountries(),
                        initial=self.ia.country or guess_country(self.event),
                    ),
                ),
            ]
        )

    def checkout_prepare(self, request, cart):
        print("MoneticoPayment.checkout_prepare", file=sys.stderr)
        cs = cart_session(request)
        request.session["payment_moneticopayment_itemcount"] = cart["itemcount"]
        request.session["payment_moneticopayment_total"] = self._decimal_to_int(
            cart["total"]
        )
        request.session["payment_moneticopayment_uuid4"] = str(uuid.uuid4())
        request.session["payment_moneticopayment_event_slug"] = self.event.slug
        request.session[
            "payment_moneticopayment_organizer_slug"
        ] = self.event.organizer.slug
        request.session["payment_moneticopayment_email"] = cs["email"]
        return super().checkout_prepare(request, cart)

    def payment_prepare(
        self, request: HttpRequest, payment: OrderPayment
    ) -> bool | str:
        print("MoneticoPayment.payment_prepare", file=sys.stderr)
        request.session["payment_moneticopayment_payment"] = payment.pk
        return True

    def payment_is_valid_session(self, request):
        print("MoneticoPayment.payment_is_valid_session", file=sys.stderr)
        return True

    def execute_payment(self, request: HttpRequest, payment: OrderPayment):
        print("MoneticoPayment.execute_payment", file=sys.stderr)
        # payment.confirm()
        signed_uuid4 = get_signed_uuid4(request)
        request.session["monetico_payment_info"] = {
            "order_code": payment.order.code,
            "order_secret": payment.order.secret,
            "payment_id": payment.pk,
            "amount": int(100 * payment.amount),
            "merchant_id": self.settings.get("merchant_id"),
        }
        url = (
            build_absolute_uri(
                request.event, "plugins:pretix_monetico:monetico.redirect"
            )
            + "?suuid4="
            + signed_uuid4
        )
        print("MoneticoPayment.execute_payment url:{}".format(url), file=sys.stderr)
        return url

    def get_monetico_locale(self, request):
        languageDjango = get_language()
        localeDjango = to_locale(languageDjango)
        baseLocale = localeDjango[0:2]
        subLocale = localeDjango[3:5].upper()
        if subLocale == "":
            subLocale = baseLocale.upper()
        locale = "{}-{}".format(baseLocale, subLocale)
        return locale

    def _decimal_to_int(self, amount):
        places = settings.CURRENCY_PLACES.get(self.event.currency, 2)
        return int(amount * 10**places)

    def checkout_confirm_render(self, request):
        print("MoneticoPayment.checkout_confirm_render", file=sys.stderr)
        ctx = {}
        template = get_template("pretix_monetico/checkout_payment_form.html")
        return template.render(ctx)

    def order_pending_mail_render(self, order) -> str:
        print("MoneticoPayment.order_pending_mail_render", file=sys.stderr)
        template = get_template("pretix_monetico/email/order_pending.txt")
        ctx = {}
        return template.render(ctx)

    def payment_pending_render(self, request: HttpRequest, payment: OrderPayment):
        print("MoneticoPayment.payment_pending_render", file=sys.stderr)
        template = get_template("pretix_monetico/pending.html")
        ctx = {}
        return template.render(ctx)

    def payment_control_render(self, request: HttpRequest, payment: OrderPayment):
        print("MoneticoPayment.payment_control_render", file=sys.stderr)
        template = get_template("pretix_monetico/control.html")
        ctx = {
            "request": request,
            "event": self.event,
            "payment": payment,
            "payment_info": payment.info_data,
            "order": payment.order,
        }
        return template.render(ctx)

    def payment_form(self, request: HttpRequest) -> Form:
        """
        This is called by the default implementation of :py:meth:`payment_form_render`
        to obtain the form that is displayed to the user during the checkout
        process. The default implementation constructs the form using
        :py:attr:`payment_form_fields` and sets appropriate prefixes for the form
        and all fields and fills the form with data form the user's session.

        If you overwrite this, we strongly suggest that you inherit from
        ``PaymentProviderForm`` (from this module) that handles some nasty issues about
        required fields for you.
        """
        form = self.payment_form_class(
            data=(
                request.POST
                if request.method == "POST"
                and request.POST.get("payment") == self.identifier
                else None
            ),
            prefix="payment_%s" % self.identifier,
            initial={
                k.replace("payment_%s_" % self.identifier, ""): v
                for k, v in request.session.items()
                if k.startswith("payment_%s_" % self.identifier)
            },
        )
        form.fields = self.payment_form_fields

        for k, v in form.fields.items():
            v._required = v.required
            v.required = False
            v.widget.is_required = False

        return form
