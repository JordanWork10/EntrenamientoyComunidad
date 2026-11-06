"""V132.09F3: acciones POST seguras para revisar novedades de espacios."""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import (
    Http404,
    HttpResponseBadRequest,
    HttpResponseRedirect,
)
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts.models import NotificationReadState
from apps.accounts.notification_read_service import (
    mark_all_as_read,
    mark_as_read,
)

from .models import SpaceProviderProfile
from .space_notification_feed_v13209 import (
    get_space_provider_notification_feed,
)


def _require_verified_provider(user):

    allowed = SpaceProviderProfile.objects.filter(
        user_id=user.pk,
        verification_status=(
            SpaceProviderProfile.VerificationStatus.VERIFIED
        ),
        is_public=True,
    ).exists()

    if not allowed:
        raise Http404(
            "Centro de Espacios no disponible."
        )


def _back_to_dashboard():

    return HttpResponseRedirect(
        reverse("spaces:dashboard")
        + "#novedades-espacios"
    )


@login_required(login_url="accounts:login")
@require_POST
def mark_space_notification_read(request):

    _require_verified_provider(
        request.user
    )

    available = get_space_provider_notification_feed(
        request.user
    )["space_notification_available_keys"]

    try:

        mark_as_read(
            request.user,
            NotificationReadState.Scope.SPACE,
            [
                request.POST.get(
                    "notification_key",
                    "",
                )
            ],
            available,
        )

    except ValidationError:

        return HttpResponseBadRequest(
            "Clave de novedad no válida."
        )

    return _back_to_dashboard()


@login_required(login_url="accounts:login")
@require_POST
def mark_all_space_notifications_read(request):

    _require_verified_provider(
        request.user
    )

    available = get_space_provider_notification_feed(
        request.user
    )["space_notification_available_keys"]

    mark_all_as_read(
        request.user,
        NotificationReadState.Scope.SPACE,
        available,
    )

    return _back_to_dashboard()