from django.utils.translation import gettext_lazy
from . import __version__

try:
    from pretix.base.plugins import PluginConfig
except ImportError:
    raise RuntimeError("Please use pretix 4.0 or above to run this plugin!")


class PluginApp(PluginConfig):
    default = True
    name = "pretix_monetico"
    verbose_name = "Monetico Pretix payment plugin"

    class PretixPluginMeta:
        author = "Ronan Le Meillat"
        picture = "pretix_monetico/monetico-logo.svg"
        name = gettext_lazy("Monetico Pretix payment plugin")
        description = gettext_lazy("plugin for accepting Monetico payments")
        visible = True
        version = __version__
        category = "PAYMENT"
        compatibility = "pretix>=4.0.0"

    def ready(self):
        from . import signals  # NOQA


