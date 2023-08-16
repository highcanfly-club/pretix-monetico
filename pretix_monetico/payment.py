import base64
import json
import sys
import uuid
from collections import OrderedDict
from Crypto.Cipher import AES
from Crypto.Hash import SHA256
from datetime import datetime
from decimal import Decimal
from django import forms
from django.conf import settings
from django.core.signing import Signer
from django.forms import Form
from django.http import HttpRequest
from django.template.loader import get_template
from django.utils.crypto import get_random_string
from django.utils.translation import get_language, gettext_lazy as _, to_locale
from django_countries.fields import Country
from pretix.base.forms.questions import guess_country
from pretix.base.models import Event, InvoiceAddress, Order, OrderPayment
from pretix.base.payment import BasePaymentProvider
from pretix.helpers.countries import CachedCountries
from pretix.multidomain.urlreverse import build_absolute_uri
from pretix.presale.views.cart import cart_session

from pretix_monetico.moneticoPaiementEpt import (
    MoneticoPaiement_Ept,
    MoneticoPaiement_Hmac,
)

MONETICOPAIEMENT_VERSION = "3.0"


def get_crypto_key():
    bKey = bytes(settings.SECRET_KEY, "utf-8")
    hash_object = SHA256.new(data=bKey)
    return hash_object.digest()


def encrypt(key: bytes, data):
    header = b"header"
    cipher = AES.new(key, AES.MODE_CCM)
    cipher.update(header)
    ciphertext, tag = cipher.encrypt_and_digest(data)

    json_k = ["nonce", "header", "ciphertext", "tag"]
    json_v = [
        base64.b64encode(x).decode("utf-8")
        for x in (cipher.nonce, header, ciphertext, tag)
    ]
    bJson = bytes(json.dumps(dict(zip(json_k, json_v))), "utf-8")
    out = base64.b64encode(bJson).decode("utf-8")
    return out


def decrypt(key, b64_input):
    json_input = base64.b64decode(b64_input)
    try:
        b64 = json.loads(json_input)
        json_k = ["nonce", "header", "ciphertext", "tag"]
        jv = {k: base64.b64decode(b64[k]) for k in json_k}

        cipher = AES.new(key, AES.MODE_CCM, nonce=jv["nonce"])
        cipher.update(jv["header"])
        plaintext = cipher.decrypt_and_verify(jv["ciphertext"], jv["tag"])
        return plaintext.decode("utf-8")
    except (ValueError, KeyError):
        return ""


def get_signed_uuid4(request):
    signer = Signer()
    uuid4_signed_bytes = signer.sign(
        request.session["payment_moneticopayment_uuid4"]
    ).encode("ascii")
    signed_uuid4 = uuid4_signed_bytes.hex().upper()
    return signed_uuid4


def get_signed_string(instr: str):
    signer = Signer()
    signed_bytes = signer.sign(instr).encode("ascii")
    signed_str = signed_bytes.hex().upper()
    return signed_str


def check_signed_string(instr: str):
    signer = Signer()
    signed_bytes = bytes.fromhex(instr)
    signed = signed_bytes.decode("ascii")
    try:
        original = signer.unsign(signed)
    except:
        original = None
    return original


def check_signed_uuid4(signed_uuid4):
    signer = Signer()
    uuid4_signed_bytes = bytes.fromhex(signed_uuid4)
    uuid4_signed = uuid4_signed_bytes.decode("ascii")
    return signer.unsign(uuid4_signed)


def getNonce(request):
    if "_monetico_nonce" not in request.session:
        request.session["_monetico_nonce"] = get_random_string(32)
    return request.session["_monetico_nonce"]


# TODO implement verify_response in payment.py
def verify_response(uri):
    return True


# TODO implement get_object_response in payment.py
def get_object_response(uri):
    return """
{}
"""


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
                        max_length=50,
                    ),
                ),
                (
                    "line2",
                    forms.CharField(
                        label=_("Card Holder Address Complement"),
                        required=False,
                        max_length=50,
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
        request.session["payment_moneticopayment_total"] = str(cart["total"])
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
            "amount": str(payment.amount),
            "currency": self.event.currency,
            "merchant_id": self.settings.get("merchant_id"),
            "organizer": self.event.organizer.slug,
            "event": self.event.slug,
        }

        # decrypto = decrypt(key,crypto)
        url = (
            build_absolute_uri(
                request.event, "plugins:pretix_monetico:monetico.redirect"
            )
            + "?suuid4="
            + signed_uuid4
        )
        print("MoneticoPayment.execute_payment url:{}".format(url), file=sys.stderr)
        return url

    def get_monetico_locale(self):
        languageDjango = get_language()
        localeDjango = to_locale(languageDjango)
        baseLocale = localeDjango[0:2]
        return baseLocale.upper()

    def get_monetico_paiement(self, request=None):
        query = ""
        if request:
            query = "?suuid4={}".format(get_signed_uuid4(request))
        return MoneticoPaiement_Ept(
            MONETICOPAIEMENT_VERSION=MONETICOPAIEMENT_VERSION,
            MONETICOPAIEMENT_KEY=self.settings.get("monetico_key"),
            MONETICOPAIEMENT_EPTNUMBER=self.settings.get("monetico_ept_number"),
            MONETICOPAIEMENT_URLSERVER=self.settings.get("monetico_url_server"),
            MONETICOPAIEMENT_URLPAYMENT=self.settings.get("monetico_payment_url"),
            MONETICOPAIEMENT_COMPANYCODE=self.settings.get("monetico_company_code"),
            MONETICOPAIEMENT_URLOK=build_absolute_uri(
                self.event, "plugins:pretix_monetico:monetico.ok"
            )
            + query,
            MONETICOPAIEMENT_URLKO=build_absolute_uri(
                self.event, "plugins:pretix_monetico:monetico.nok"
            )
            + query,
            sLang=self.get_monetico_locale(),
        )

    def get_oHMac(self):
        oEpt = self.get_monetico_paiement()
        return MoneticoPaiement_Hmac(oEpt)

    def get_monetico_params(self, request):
        # for key, value in request.session.items():
        #     print("{} => {}".format(key, value), file=sys.stderr)
        sLang = self.get_monetico_locale()
        sDate = datetime.now().strftime("%d/%m/%Y:%H:%M:%S")
        sMontant = request.session["monetico_payment_info"]["amount"]
        sDevise = request.session["monetico_payment_info"]["currency"]
        sReference = request.session["monetico_payment_info"]["order_code"]
        sEmail = request.session["payment_moneticopayment_email"]
        key = get_crypto_key()
        payment_info = bytes(
            json.dumps(request.session["monetico_payment_info"]), "utf-8"
        )
        crypto = encrypt(key, payment_info)
        payment_info_signed = get_signed_string(crypto)
        sTexteLibre = payment_info_signed
        contexteCommand = {
            "billing": {
                "firstName": request.session["payment_moneticopayment_firstname"],
                "lastName": request.session["payment_moneticopayment_lastname"],
                "addressLine1": request.session["payment_moneticopayment_line1"],
                "city": request.session["payment_moneticopayment_city"],
                "postalCode": request.session["payment_moneticopayment_postal_code"],
                "country": request.session["payment_moneticopayment_country"],
                "email": sEmail,
            }
        }
        if len(request.session["payment_moneticopayment_line2"]) > 0:
            contexteCommand["billing"]["addressLine2"] = request.session[
                "payment_moneticopayment_line2"
            ]
        utf8ContexteCommande = json.dumps(contexteCommand).encode("utf8")
        sContexteCommande = base64.b64encode(utf8ContexteCommande).decode()
        oMac = self.get_oHMac()
        oEpt = self.get_monetico_paiement(request)
        sChaineMAC = "*".join(
            [
                f"TPE={oEpt.sNumero}",
                f"contexte_commande={sContexteCommande}",
                f"date={sDate}",
                f"dateech1={''}",
                f"dateech2={''}",
                f"dateech3={''}",
                f"dateech4={''}",
                f"lgue={sLang}",
                f"mail={request.session['payment_moneticopayment_email']}",
                f"montant={sMontant}{sDevise}",
                f"montantech1={''}",
                f"montantech2={''}",
                f"montantech3={''}",
                f"montantech4={''}",
                f"nbrech={''}",
                f"reference={sReference}",
                f"societe={oEpt.sCodeSociete}",
                f"texte-libre={sTexteLibre}",
                f"url_retour_err={oEpt.sUrlKo}",
                f"url_retour_ok={oEpt.sUrlOk}",
                f"version={oEpt.sVersion}",
            ]
        )
        print(sChaineMAC, file=sys.stderr)
        hmac = oMac.computeHMACSHA1(sChaineMAC)

        form = (
            '''<input type="hidden" name="version"           id="version"           value="'''
            + oEpt.sVersion
            + '''" />
        <input type="hidden" name="TPE"               id="TPE"               value="'''
            + oEpt.sNumero
            + '''" />
        <input type="hidden" name="contexte_commande" id="contexte_commande" value="'''
            + sContexteCommande
            + '''" />
        <input type="hidden" name="date"              id="date"              value="'''
            + sDate
            + '''" />
        <input type="hidden" name="montant"           id="montant"           value="'''
            + sMontant
            + sDevise
            + '''" />
        <input type="hidden" name="reference"         id="reference"         value="'''
            + sReference
            + '''" />
        <input type="hidden" name="MAC"               id="MAC"               value="'''
            + hmac
            + '''" />
        <input type="hidden" name="url_retour_ok"     id="url_retour_ok"     value="'''
            + oEpt.sUrlOk
            + '''" />
        <input type="hidden" name="url_retour_err"    id="url_retour_err"    value="'''
            + oEpt.sUrlKo
            + '''" />
        <input type="hidden" name="lgue"              id="lgue"              value="'''
            + sLang
            + '''" />
        <input type="hidden" name="societe"           id="societe"           value="'''
            + oEpt.sCodeSociete
            + '''" />
        <input type="hidden" name="texte-libre"       id="texte-libre"       value="'''
            + sTexteLibre
            + '''" />
        <input type="hidden" name="mail"              id="mail"              value="'''
            + sEmail
            + '''" />
        <input type="hidden" name="nbrech"            id="nbrech"            value="'''
            + ""
            + '''" />
        <input type="hidden" name="dateech1"          id="dateech1"          value="'''
            + ""
            + '''" />
        <input type="hidden" name="montantech1"       id="montantech1"       value="'''
            + ""
            + '''" />
        <input type="hidden" name="dateech2"          id="dateech2"          value="'''
            + ""
            + '''" />
        <input type="hidden" name="montantech2"       id="montantech2"       value="'''
            + ""
            + '''" />
        <input type="hidden" name="dateech3"	      id="dateech3"          value="'''
            + ""
            + '''" />
        <input type="hidden" name="montantech3"       id="montantech3"       value="'''
            + ""
            + '''" />
        <input type="hidden" name="dateech4"	      id="dateech4"          value="'''
            + ""
            + '''" />
        <input type="hidden" name="montantech4"       id="montantech4"       value="'''
            + ""
            + """" />"""
        )
        print(form, file=sys.stderr)
        return {"html": form, "action": oEpt.sUrlPaiement, "hmac": hmac}

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
