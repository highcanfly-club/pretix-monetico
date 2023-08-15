from django.urls import re_path
from pretix.multidomain import event_url
from . import views

event_patterns = [
    re_path(r'^monetico/payment/ok',
            views.ok, name='monetico.ok'),
    re_path(r'^monetico/payment/nok',
            views.nok, name='monetico.nok'),
    event_url(r'^monetico/payment/redirect',
              views.redirectview, name='monetico.redirect'),
]

urlpatterns = [
    re_path(r"^plugins/payment/monetico", views.monetico_return, name="monetico.return"),
]
