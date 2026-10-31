"""V131.74: bloqueos de reservas individuales canceladas por el profesional.

Ejecutar:
python manage.py test apps.bookings.tests_professional_slot_lock_v13174 --verbosity 2
"""

from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.professionals.models import (
    ProfessionalCategory,
    ProfessionalProfile,
    ProfessionalService,
    ProfessionalServiceAvailability,
    ProfessionalSpecialty,
)

from .models import Booking, BookingHistory
from .services import create_booking, get_available_slots


class ProfessionalSlotCancellationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.professional = User.objects.create_user(
            username='profesional_v13174',
            email='profesional_v13174@example.test',
            password='test',
        )
        self.member = User.objects.create_user(
            username='miembro_v13174',
            email='miembro_v13174@example.test',
            password='test',
        )
        self.other_member = User.objects.create_user(
            username='otro_miembro_v13174',
            email='otro_miembro_v13174@example.test',
            password='test',
        )

        category = ProfessionalCategory.objects.create(
            name='Entrenamiento V13174',
            slug='entrenamiento-v13174',
        )
        specialty = ProfessionalSpecialty.objects.create(
            name='Sesiones V13174',
            slug='sesiones-v13174',
            category=category,
        )
        self.profile = ProfessionalProfile.objects.create(
            user=self.professional,
            category=category,
            specialty=specialty,
            bio='Profesional de prueba.',
            offers_online=True,
            verification_status=ProfessionalProfile.VerificationStatus.VERIFIED,
            is_public=True,
        )
        self.day = timezone.localdate() + timedelta(days=14)
        self.service = self._make_service('Primera sesión', 20000)
        self.other_service = self._make_service('Segunda sesión', 30000)

    def _make_service(self, name, price):
        service = ProfessionalService.objects.create(
            professional_profile=self.profile,
            name=name,
            description='Servicio profesional de prueba.',
            mode=ProfessionalService.ServiceMode.ONLINE,
            duration_minutes=60,
            price=price,
            publication_status=ProfessionalService.PublicationStatus.PUBLISHED,
        )
        ProfessionalServiceAvailability.objects.create(
            service=service,
            weekday=self.day.weekday(),
            start_time=time(9, 0),
            end_time=time(12, 0),
            valid_from=self.day,
            is_active=True,
        )
        return service

    def _book_first_slot(self):
        return create_booking(
            user=self.member,
            service=self.service,
            session_date=self.day,
            start_time=time(9, 0),
            end_time=time(10, 0),
        )

    def _slot_times(self, service):
        return [
            (slot['start_time'], slot['end_time'])
            for slot in get_available_slots(service, self.day)
        ]

    def _cancel_as_professional(self, booking):
        self.client.force_login(self.professional)
        response = self.client.post(
            reverse('bookings:professional_cancel', args=[booking.pk]),
            data={'cancellation_reason': 'No podré atender esta sesión.'},
        )
        self.assertEqual(response.status_code, 302)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CANCELLED)
        self.assertTrue(
            BookingHistory.objects.filter(
                booking=booking,
                action=BookingHistory.Action.CANCELLED,
                changed_by=self.professional,
            ).exists()
        )

    def test_professional_cancellation_closes_slot_in_all_services(self):
        booking = self._book_first_slot()
        self._cancel_as_professional(booking)

        self.assertNotIn(
            (time(9, 0), time(10, 0)),
            self._slot_times(self.service),
        )
        self.assertNotIn(
            (time(9, 0), time(10, 0)),
            self._slot_times(self.other_service),
        )
        self.assertIn(
            (time(10, 0), time(11, 0)),
            self._slot_times(self.other_service),
        )

    def test_direct_booking_cannot_bypass_professional_block(self):
        booking = self._book_first_slot()
        self._cancel_as_professional(booking)

        with self.assertRaises(ValidationError):
            create_booking(
                user=self.other_member,
                service=self.other_service,
                session_date=self.day,
                start_time=time(9, 0),
                end_time=time(10, 0),
            )

        self.assertFalse(
            Booking.objects.filter(
                booked_by=self.other_member,
                session_date=self.day,
            ).exists()
        )

    def test_member_cancellation_reopens_slot_for_other_members(self):
        booking = self._book_first_slot()
        self.client.force_login(self.member)
        response = self.client.post(
            reverse('bookings:cancel_my_booking', args=[booking.pk]),
            data={'cancellation_reason': 'No podré asistir ese día.'},
        )
        self.assertEqual(response.status_code, 302)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CANCELLED)

        self.assertIn(
            (time(9, 0), time(10, 0)),
            self._slot_times(self.service),
        )

        new_booking = create_booking(
            user=self.other_member,
            service=self.other_service,
            session_date=self.day,
            start_time=time(9, 0),
            end_time=time(10, 0),
        )
        self.assertEqual(new_booking.status, Booking.Status.PENDING)

    def test_active_booking_blocks_other_services_before_cancellation(self):
        self._book_first_slot()
        self.assertNotIn(
            (time(9, 0), time(10, 0)),
            self._slot_times(self.other_service),
        )
