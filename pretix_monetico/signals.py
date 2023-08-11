# Register your receivers here
# Register your receivers here
import sys
from django.dispatch import receiver
from django.http import HttpRequest, HttpResponse
from django.urls import resolve
from pretix.base.middleware import _merge_csp, _parse_csp, _render_csp
from pretix.base.signals import register_payment_providers
from pretix.presale.signals import process_response
from .payment import getNonce


@receiver(register_payment_providers, dispatch_uid="payment_monetico")
def register_payment_provider(sender, **kwargs):
    from .payment import MoneticoPayment

    return MoneticoPayment


@receiver(signal=process_response, dispatch_uid="payment_monetico_middleware_resp")
def signal_process_response(
    sender, request: HttpRequest, response: HttpResponse, **kwargs
):
    url = resolve(request.path_info)
    if url.url_name == "event.checkout" or url.url_name == "monetico.redirect":
        if "Content-Security-Policy" in response:
            h = _parse_csp(response["Content-Security-Policy"])
        else:
            h = {}
        csps = {
            "script-src": [
                "'nonce-{}'".format(getNonce(request)),
            ],
        }

        _merge_csp(h, csps)
        if h:
            response["Content-Security-Policy"] = _render_csp(h)

    return response
