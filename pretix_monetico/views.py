import base64
import json
import sys
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import resolve
from django.core.signing import Signer
from django.utils.translation import gettext_lazy as _
from django_scopes import scope
from pretix.base.models import Event, OrderPayment, Organizer
from pretix.multidomain.urlreverse import eventreverse
from django.views.decorators.csrf import csrf_exempt
from urllib.parse import parse_qs, urlparse

from .payment import (
    MoneticoPayment,
    check_signed_string,
    check_signed_uuid4,
    decrypt,
    get_crypto_key,
    get_object_response,
    getNonce,
    verify_response,
)


def ok(request, *args, **kwargs):
    print("views.effectue", file=sys.stderr)
    print(request.build_absolute_uri(), file=sys.stderr)
    suuid4 = request.GET.get("suuid4")
    pid = check_signed_uuid4(suuid4)
    if pid == request.session["payment_moneticopayment_uuid4"]:
        if request.session.get("monetico_payment_info"):
            monetico_payment_info = request.session.get("monetico_payment_info")
            payment = OrderPayment.objects.get(pk=monetico_payment_info["payment_id"])
        else:
            payment = None
        if payment:
            return redirect(
                eventreverse(
                    request.event,
                    "presale:event.order",
                    kwargs={
                        "order": payment.order.code,
                        "secret": payment.order.secret,
                    },
                )
            )
    return HttpResponse(_("unkown error"), status=200)


def nok(request, *args, **kwargs):
    print("views.nok", file=sys.stderr)
    return annule(request, kwargs)

def annule(request, *args, **kwargs):
    print("views.annule", file=sys.stderr)
    pid = request.GET.get("paymentId")
    if pid == request.session["payment_moneticopayment_uuid4"]:
        check = verify_response(request.build_absolute_uri())
        if check:
            if request.session.get("monetico_payment_info"):
                monetico_payment_info = request.session.get("monetico_payment_info")
                payment = OrderPayment.objects.get(
                    pk=monetico_payment_info["payment_id"]
                )
                payment.fail()
                return redirect(
                    eventreverse(
                        request.event,
                        "presale:event.order",
                        kwargs={
                            "order": payment.order.code,
                            "secret": payment.order.secret,
                        },
                    )
                )
    return HttpResponse(_("canceled"), status=500)


def redirectview(request, *args, **kwargs):
    # for key, value in request.session.items():
    #     print('{} => {}'.format(key, value), file=sys.stderr)
    print("views.redirect", file=sys.stderr)
    url = resolve(request.path_info)
    print("MoneticoPayment.redirectview {}".format(url.url_name), file=sys.stderr)
    spid = request.GET.get("suuid4")
    pid = check_signed_uuid4(spid)

    print(pid, file=sys.stderr)
    if pid == request.session["payment_moneticopayment_uuid4"]:
        event_slug = request.session["payment_moneticopayment_event_slug"]
        organizer_slug = request.session["payment_moneticopayment_organizer_slug"]
        organizer = Organizer.objects.filter(slug=organizer_slug).first()
        with scope(organizer=organizer):
            event = Event.objects.filter(slug=event_slug).first()
        payment_provider = MoneticoPayment(event)
        monetico_params = payment_provider.get_monetico_params(request)
        ctx = {
            "nonce": getNonce(request),
            "action": monetico_params["action"],
            "hmac": monetico_params["hmac"],
            "html": monetico_params["html"],
        }
        r = render(request, "pretix_monetico/redirect.html", ctx)
        return r

    return HttpResponse(_("Server Error"), status=500)

@csrf_exempt
def monetico_return(request, *args, **kwargs):
    if request.method == "GET":      
        access_method = request.GET
    elif request.method == "POST":
        access_method = request.POST
    
    texte_libre = access_method.get("texte-libre")
    payment_info_encrypted = check_signed_string(texte_libre)
    if payment_info_encrypted:
        # sign is correct
        key = get_crypto_key()
        payment_info_str = decrypt(key, payment_info_encrypted)
        payment_info = json.loads(payment_info_str)
        organizer = Organizer.objects.filter(slug=payment_info["organizer"]).first()
        with scope(organizer=organizer):
            event = Event.objects.filter(slug=payment_info["event"]).first()
            payment = OrderPayment.objects.get(pk=payment_info["payment_id"])
            payment_provider = MoneticoPayment(event)
            oHMac = payment_provider.get_oHMac()
            Certification = {}
            for key in access_method:
                if key == "MAC":
                    continue
                Certification[key] = access_method.get(key)
            sorted_params = dict(sorted(Certification.items()))
            print(sorted_params, file=sys.stderr)
            sChaineMAC = "*".join(
                "{}={}".format(key, value) for key, value in sorted_params.items()
            )
            bHMac = oHMac.bIsValidHmac(sChaineMAC, access_method.get("MAC"))
            if bHMac:
                if Certification["code-retour"] == "Annulation":
                    payment.fail()
                    return HttpResponse("NOK", status=200)

                elif (
                    Certification["code-retour"] == "payetest"
                    or Certification["code-retour"] == "paiement"
                ):
                    info_data = json.loads(base64.b64decode(Certification["authentification"]))
                    info_data['card'] = access_method.get('cbmasquee')
                    info_data['exp'] = access_method.get('vld')
                    info_data['date'] = access_method.get('date')
                    info_data['ref'] = access_method.get('reference')
                    info_data['numauto'] = access_method.get('numauto')
                    payment.info = json.dumps(info_data)
                    payment.confirm()
                    return HttpResponse("OK", status=200)
    return HttpResponse(
        _("Server Error signature is wrong"),
        status=500,
    )
