"""Panel reutilizable solo en los dos dashboards existentes."""

from datetime import timedelta

from django import template
from django.db.models import Q
from django.utils import timezone

from apps.bookings.models import Booking, BookingSessionReview
from apps.professionals.models import ProfessionalProfile


register = template.Library()


@register.inclusion_tag(
    'bookings/partials/session_attention_panel.html',
    takes_context=True
)
def session_attention_panel(context):

    request = context.get('request')

    if request is None or not request.user.is_authenticated:
        return {}

    match = getattr(request, 'resolver_match', None)
    page = getattr(match, 'view_name', None)

    now = timezone.now()

    # ==========================================
    # PANEL DEL MIEMBRO
    # ==========================================

    if page == 'accounts:dashboard':

        pending = list(
            BookingSessionReview.objects.filter(
                booking__booked_by=request.user,
                booking__status=Booking.Status.COMPLETED,
                status=BookingSessionReview.Status.PENDING,
                expires_at__gt=now,
            )
            .select_related(
                'booking__professional_profile__user'
            )
            .order_by('-created_at')[:3]
        )

        unrated = list(
            BookingSessionReview.objects.filter(
                booking__booked_by=request.user,
                booking__status=Booking.Status.COMPLETED,
                status=BookingSessionReview.Status.CONFIRMED,
                rating__isnull=True,
                responded_at__gte=now-timedelta(days=7),
            )
            .select_related(
                'booking__professional_profile__user'
            )
            .order_by('-responded_at')[:3]
        )

        return {
            'panel_mode': 'member',
            'pending_reviews': pending,
            'unrated_reviews': unrated,
        }

    # ==========================================
    # PANEL DEL PROFESIONAL
    # ==========================================

    if page == 'professionals:dashboard':

        profile = getattr(
            request.user,
            'professional_profile',
            None
        )

        if (
            not profile
            or profile.verification_status
            != ProfessionalProfile.VerificationStatus.VERIFIED
        ):
            return {}

        local_now = timezone.localtime()

        ready = list(
            Booking.objects.filter(
                professional_profile=profile,
                status=Booking.Status.CONFIRMED,
            )
            .filter(
                Q(session_date__lt=local_now.date())
                |
                Q(
                    session_date=local_now.date(),
                    end_time__lte=local_now.time().replace(
                        tzinfo=None
                    )
                )
            )
            .select_related('booked_by')
            .order_by(
                '-session_date',
                '-end_time'
            )[:3]
        )

        return {
            'panel_mode': 'professional',
            'ready_sessions': ready,
        }

    return {}