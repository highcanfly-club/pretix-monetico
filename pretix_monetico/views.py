import sys
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import resolve
from django.utils.translation import gettext_lazy as _
from django_scopes import scope
from pretix.base.models import Event, OrderPayment, Organizer
from pretix.multidomain.urlreverse import eventreverse
from urllib.parse import parse_qs, urlparse

from .payment import MoneticoPayment, check_signed_uuid4, get_object_response, getNonce, verify_response


def ok(request, *args, **kwargs):
    print('views.effectue', file=sys.stderr)
    pid = request.GET.get('paymentId')
    if pid == request.session['payment_moneticopayment_uuid4']:
        if request.session.get('monetico_payment_info'):
            monetico_payment_info = request.session.get('monetico_payment_info')
            payment = OrderPayment.objects.get(pk=monetico_payment_info["payment_id"])
        else:
            payment = None
        if payment:
            check = verify_response(request.build_absolute_uri())
            if check:
                if get_response_code(request) == "00000":
                    payment.info_data = get_object_response(request.build_absolute_uri())
                    payment.confirm()
                    return redirect(eventreverse(request.event, 'presale:event.order', kwargs={
                        'order': payment.order.code,
                        'secret': payment.order.secret
                    }) + '?paid=yes')
                else:
                    payment.fail()
                    return redirect(eventreverse(request.event, 'presale:event.order', kwargs={
                        'order': payment.order.code,
                        'secret': payment.order.secret
                    }))
    return HttpResponse(_("unkown error"), status=200)


def nok(request, *args, **kwargs):
    print('views.nok', file=sys.stderr)
    return annule(request, kwargs)


def get_response_code(request):
    uri = request.build_absolute_uri()
    url_parsed = urlparse(uri)
    query = parse_qs(url_parsed.query)  # dictionnary
    error = query["error"][0]
    return error

def annule(request, *args, **kwargs):
    print('views.annule', file=sys.stderr)
    pid = request.GET.get('paymentId')
    if pid == request.session['payment_moneticopayment_uuid4']:
        check = verify_response(request.build_absolute_uri())
        if check:
            if request.session.get('monetico_payment_info'):
                monetico_payment_info = request.session.get('monetico_payment_info')
                payment = OrderPayment.objects.get(pk=monetico_payment_info["payment_id"])
                payment.fail()
                return redirect(eventreverse(request.event, 'presale:event.order', kwargs={
                    'order': payment.order.code,
                    'secret': payment.order.secret
                }))
    return HttpResponse(_("canceled"), status=500)

def redirectview(request, *args, **kwargs):
    # for key, value in request.session.items():
    #     print('{} => {}'.format(key, value), file=sys.stderr)
    print('views.redirect', file=sys.stderr)
    url = resolve(request.path_info)
    print("MoneticoPayment.redirectview {}".format(url.url_name), file=sys.stderr)
    spid = request.GET.get('suuid4')
    pid = check_signed_uuid4(spid)
    print(pid, file=sys.stderr)
    if pid == request.session['payment_moneticopayment_uuid4']:
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
            'hmac': monetico_params["hmac"],
            "html": monetico_params["html"]
        }
        r = render(request, 'pretix_monetico/redirect.html', ctx)
        return r

    return HttpResponse(_('Server Error'), status=500)