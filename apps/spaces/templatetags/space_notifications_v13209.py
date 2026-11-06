"""Etiqueta V132.09F3 para renderizar las novedades del proveedor."""

from django import template

from apps.spaces.space_notification_feed_v13209 import (
    get_space_provider_notification_feed,
)


register = template.Library()


@register.inclusion_tag(
    "spaces/_space_notifications_v13209.html",
    takes_context=True,
)
def space_notifications_panel(context):

    request = context.get("request")

    if (
        request is None
        or not request.user.is_authenticated
    ):
        return {}

    return get_space_provider_notification_feed(
        request.user
    )