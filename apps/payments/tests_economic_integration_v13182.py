"""V131.82: integración ORM de tres orígenes económicos en una misma cuenta.

Instalar como: apps/payments/tests_economic_integration_v13182.py

python manage.py test apps.payments.tests_economic_integration_v13182 --verbosity 2

Django utiliza su base de datos de PRUEBAS. No crea datos en la base habitual.
No cambia vistas, modelos ni reglas de negocio del proyecto.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.activities.models import Activity, ActivityCategory
from apps.bookings.models import Booking
from apps.bookings.services import create_booking
from apps.locations.models import Commune, Region
from apps.professionals.models import (
    ProfessionalCategory,
    ProfessionalProfile,
    ProfessionalService,
    ProfessionalServiceAvailability,
    ProfessionalSpecialty,
)
from apps.spaces.models import (
    Space, SpaceAvailability, SpaceBooking,
    SpaceProviderProfile, SpaceType,
)

from .models import Payment, Refund, Settlement, SpaceCancellationRequest
from .services.professional_booking_payments import (
    ProfessionalBookingPaymentError,
    approve_professional_booking_payment,
    cancel_professional_booking_with_refund,
    open_professional_booking_payment,
)
from .services.space_cancellations import (
    SpaceCancellationError,
    request_paid_space_cancellation,
)
from .services.space_policy import SPACE_POLICY_VERSION


@override_settings(PAYMENTS_SANDBOX=True)
class EconomicIntegrationV13182Tests(TestCase):
    """Tres pagos simultáneos: actividad, sesión y arriendo, sin cruzar fondos."""

    def setUp(self):
        User = get_user_model()
        self.member = User.objects.create_user(
            username='member_v13182', email='member_v13182@example.test',
            password='test',
        )
        self.stranger = User.objects.create_user(
            username='stranger_v13182', email='stranger_v13182@example.test',
            password='test',
        )
        self.professional = User.objects.create_user(
            username='professional_v13182', email='professional_v13182@example.test',
            password='test',
        )
        self.provider = User.objects.create_user(
            username='provider_v13182', email='provider_v13182@example.test',
            password='test',
        )
        self.admin = User.objects.create_superuser(
            username='admin_v13182', email='admin_v13182@example.test',
            password='test',
        )
        self.day = timezone.localdate() + timedelta(days=14)
        tz = timezone.get_current_timezone()
        self.prof_start = timezone.make_aware(
            datetime.combine(self.day, time(9)), tz,
        )
        self.space_start = timezone.make_aware(
            datetime.combine(self.day, time(12)), tz,
        )

        # Profesional verificado y sesión aceptada: se usa el servicio real
        # de apertura y aprobación, con la comisión del plan fijada en prueba.
        category = ProfessionalCategory.objects.create(
            name='Categoría integrada V13182', slug='categoria-integrada-v13182',
        )
        specialty = ProfessionalSpecialty.objects.create(
            name='Especialidad integrada V13182',
            slug='especialidad-integrada-v13182', category=category,
        )
        self.prof_profile = ProfessionalProfile.objects.create(
            user=self.professional, category=category, specialty=specialty,
            bio='Profesional de pruebas económicas.',
            offers_online=True, is_public=True,
            verification_status=ProfessionalProfile.VerificationStatus.VERIFIED,
        )
        self.service = ProfessionalService.objects.create(
            professional_profile=self.prof_profile,
            name='Entrenamiento V13182',
            description='Sesión individual de integración.',
            mode=ProfessionalService.ServiceMode.ONLINE,
            duration_minutes=60, price=20000,
            publication_status=ProfessionalService.PublicationStatus.PUBLISHED,
        )
        ProfessionalServiceAvailability.objects.create(
            service=self.service, weekday=self.day.weekday(),
            start_time=time(9), end_time=time(11),
            valid_from=self.day, is_active=True,
        )
        self.prof_booking = create_booking(
            user=self.member, service=self.service, session_date=self.day,
            start_time=time(9), end_time=time(10),
        )
        self.prof_booking.status = Booking.Status.CONFIRMED
        self.prof_booking.confirmed_at = timezone.now()
        self.prof_booking.save(
            update_fields=['status', 'confirmed_at', 'updated_at'],
        )
        opened = open_professional_booking_payment(
            self.prof_booking.pk, self.member,
        )
        with patch(
            'apps.payments.services.commissions.get_professional_commission_snapshot',
            return_value=SimpleNamespace(
                plan_code='professional_base',
                commission_rate_percent=Decimal('12.00'),
            ),
        ):
            self.prof_payment = approve_professional_booking_payment(
                opened.public_id, self.member,
                accepts_policy=True, accepts_sandbox=True,
            )

        # Actividad de otro tipo de oferta, ya reembolsada: historial conservado.
        activity_category = ActivityCategory.objects.create(
            name='Actividad integrada V13182',
            slug='actividad-integrada-v13182',
        )
        self.activity = Activity.objects.create(
            organizer=self.professional, professional_profile=self.prof_profile,
            activity_type=Activity.ActivityType.PROFESSIONAL,
            category=activity_category, title='Clase V13182',
            description='Clase profesional de prueba.',
            modality=Activity.Modality.ONLINE,
            date=self.day, start_time=time(15), end_time=time(16),
            capacity=10, price=8000, status=Activity.Status.PUBLISHED,
        )
        self.activity_payment = Payment.objects.create(
            payer=self.member, activity=self.activity,
            economic_scope=Payment.EconomicScope.PROFESSIONAL_ACTIVITY,
            amount_clp=8000, status=Payment.Status.REFUNDED,
            refunded_amount_clp=8000, commission_base_clp=0,
            commission_amount_clp=0, net_amount_clp=0,
            approved_at=timezone.now(),
        )
        Refund.objects.create(
            payment=self.activity_payment, requested_by=self.member,
            refund_type=Refund.RefundType.FULL,
            reason=Refund.Reason.MEMBER_CANCELLATION,
            amount_clp=8000, status=Refund.Status.PROCESSED,
            policy_percentage_snapshot=Decimal('100'),
            resolved_at=timezone.now(), processed_at=timezone.now(),
        )

        # Proveedor y arriendo: dominio distinto a profesional/actividad.
        region = Region.objects.create(
            name='Región integración V13182', code='R82',
        )
        commune = Commune.objects.create(
            name='Comuna integración V13182', code='C82', region=region,
        )
        self.provider_profile = SpaceProviderProfile.objects.create(
            user=self.provider, public_name='Proveedor V13182',
            verification_status=SpaceProviderProfile.VerificationStatus.VERIFIED,
            is_public=True,
        )
        space_type = SpaceType.objects.create(
            name='Gimnasio V13182', slug='gimnasio-v13182',
        )
        self.space = Space.objects.create(
            provider_profile=self.provider_profile, space_type=space_type,
            name='Recinto V13182', description='Espacio de integración.',
            commune=commune, address='Dirección ficticia de pruebas',
            capacity=10, hourly_price_clp=18000,
            publication_status=Space.PublicationStatus.PUBLISHED,
        )
        SpaceAvailability.objects.create(
            space=self.space, weekday=self.day.weekday(),
            start_time=time(12), end_time=time(13),
            valid_from=timezone.localdate(),
        )
        self.space_booking = SpaceBooking.objects.create(
            booked_by=self.member, space=self.space,
            provider_profile=self.provider_profile,
            session_date=self.day, start_time=time(12), end_time=time(13),
            duration_minutes=60, price_clp=18000,
            space_name_snapshot=self.space.name,
            space_type_snapshot='Gimnasio',
            provider_name_snapshot=self.provider_profile.public_name,
            address_snapshot=self.space.address,
            commune_snapshot=commune.name,
            status=SpaceBooking.Status.CONFIRMED,
            confirmed_at=timezone.now(),
        )
        self.space_payment = Payment.objects.create(
            payer=self.member, space_booking=self.space_booking,
            economic_scope=Payment.EconomicScope.SPACE_BOOKING,
            amount_clp=18000, status=Payment.Status.APPROVED,
            plan_code_snapshot='space_provider_base',
            commission_rate_percent=Decimal('10.00'),
            commission_base_clp=18000,
            commission_amount_clp=1800, net_amount_clp=16200,
            policy_version=SPACE_POLICY_VERSION,
            policy_accepted_at=timezone.now(),
            approved_at=timezone.now(),
        )

    def _cancel_professional_36h(self):
        return cancel_professional_booking_with_refund(
            self.prof_booking.pk, self.member,
            by_professional=False,
            reason='Cambio de disponibilidad personal.',
            cancelled_at=self.prof_start - timedelta(hours=36),
        )

    def _cancel_space_60h(self):
        cancel_at = self.space_start - timedelta(hours=60)
        self.space_payment.approved_at = cancel_at - timedelta(hours=3)
        self.space_payment.policy_accepted_at = self.space_payment.approved_at
        self.space_payment.save(update_fields=[
            'approved_at', 'policy_accepted_at', 'updated_at',
        ])
        with patch('django.utils.timezone.now', return_value=cancel_at):
            return request_paid_space_cancellation(
                booking_id=self.space_booking.pk, actor=self.member,
                reason='No podré ocupar el recinto reservado.',
            )

    def test_three_origin_snapshots_are_consistent(self):
        for payment in (
            self.activity_payment, self.prof_payment, self.space_payment,
        ):
            payment.full_clean()
            self.assertEqual(sum(bool(item) for item in (
                payment.activity_id, payment.professional_booking_id,
                payment.space_booking_id,
            )), 1)
        self.assertEqual(Payment.objects.count(), 3)

    def test_member_history_contains_all_three_without_double_counting(self):
        self.client.force_login(self.member)
        response = self.client.get(reverse('payments:my_payments'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['movements_total'], 3)
        self.assertEqual(response.context['activities_count'], 1)
        self.assertEqual(response.context['sessions_count'], 1)
        self.assertEqual(response.context['spaces_count'], 1)
        self.assertEqual(response.context['approved_total'], 46000)
        self.assertEqual(response.context['refunded_total'], 8000)
        self.assertEqual(response.context['retained_total'], 38000)

    def test_each_history_filter_returns_only_its_origin(self):
        self.client.force_login(self.member)
        expected = {
            'actividades': self.activity_payment.pk,
            'sesiones': self.prof_payment.pk,
            'espacios': self.space_payment.pk,
        }
        for filter_name, payment_id in expected.items():
            with self.subTest(filter_name=filter_name):
                response = self.client.get(
                    reverse('payments:my_payments') + f'?tipo={filter_name}'
                )
                self.assertEqual(
                    list(response.context['payments'].values_list('pk', flat=True)),
                    [payment_id],
                )
                # El resumen corresponde a todos los tipos, incluso filtrado.
                self.assertEqual(response.context['approved_total'], 46000)

    def test_member_can_open_each_receipt_but_stranger_gets_404(self):
        receipts = (
            ('payments:receipt', self.activity_payment.public_id),
            ('payments:professional_booking_receipt', self.prof_payment.public_id),
            ('payments:space_receipt', self.space_payment.public_id),
        )
        for name, public_id in receipts:
            url = reverse(name, kwargs={'payment_id': public_id})
            with self.subTest(receipt=name):
                self.client.force_login(self.member)
                self.assertEqual(self.client.get(url).status_code, 200)
                self.client.force_login(self.stranger)
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_stranger_history_is_empty_even_when_same_service_exists(self):
        self.client.force_login(self.stranger)
        response = self.client.get(reverse('payments:my_payments'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['movements_total'], 0)
        self.assertEqual(response.context['approved_total'], 0)

    def test_professional_income_does_not_include_space_payments(self):
        self.client.force_login(self.professional)
        response = self.client.get(reverse('payments:professional_income'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['paid_activity_count'], 1)
        self.assertEqual(response.context['paid_session_count'], 1)
        self.assertEqual(response.context['gross_total'], 28000)
        self.assertEqual(response.context['refunded_total'], 8000)
        self.assertEqual(response.context['to_settle_total'], 17600)

    def test_provider_income_does_not_include_professional_payments(self):
        self.client.force_login(self.provider)
        response = self.client.get(reverse('payments:space_income'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['totals']['gross_total'], 18000)
        self.assertEqual(response.context['totals']['refunded_total'], 0)
        self.assertEqual(response.context['totals']['net_total'], 16200)
        self.assertEqual(response.context['totals']['attempt_count'], 1)

    def test_admin_day_panels_keep_their_economies_separate(self):
        self.client.force_login(self.admin)
        space_response = self.client.get(
            reverse('payments:space_settlement_admin'),
        )
        professional_response = self.client.get(
            reverse('payments:professional_day_settlement_admin'),
        )
        self.assertEqual(space_response.status_code, 200)
        self.assertEqual(professional_response.status_code, 200)
        space_rows = space_response.context['rows']
        pro_rows = professional_response.context['rows']
        self.assertEqual(len(space_rows), 1)
        self.assertEqual(len(pro_rows), 1)
        self.assertEqual(space_rows[0]['gross_total'], 18000)
        self.assertEqual(space_rows[0]['net_total'], 16200)
        self.assertEqual(pro_rows[0]['gross_total'], 20000)
        self.assertEqual(pro_rows[0]['net_total'], 17600)

    def test_nonstaff_cannot_open_either_administrative_panel(self):
        urls = (
            reverse('payments:space_settlement_admin'),
            reverse('payments:professional_day_settlement_admin'),
        )
        for actor in (self.member, self.professional, self.provider):
            self.client.force_login(actor)
            for url in urls:
                with self.subTest(username=actor.username, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)

    def test_provider_and_professional_cannot_open_each_other_income(self):
        self.client.force_login(self.provider)
        self.assertEqual(
            self.client.get(reverse('payments:professional_income')).status_code,
            302,
        )
        self.client.force_login(self.professional)
        self.assertEqual(
            self.client.get(reverse('payments:space_income')).status_code, 302,
        )

    def test_read_only_dashboards_do_not_update_economic_records(self):
        before_payments = list(
            Payment.objects.order_by('pk').values_list(
                'pk', 'status', 'updated_at',
                'refunded_amount_clp', 'net_amount_clp',
            )
        )
        before_refunds = Refund.objects.count()
        before_settlements = Settlement.objects.count()
        self.client.force_login(self.member)
        self.client.get(reverse('payments:my_payments'))
        self.client.force_login(self.professional)
        self.client.get(reverse('payments:professional_income'))
        self.client.force_login(self.provider)
        self.client.get(reverse('payments:space_income'))
        self.client.force_login(self.admin)
        self.client.get(reverse('payments:space_settlement_admin'))
        self.client.get(reverse('payments:professional_day_settlement_admin'))
        self.assertEqual(
            list(Payment.objects.order_by('pk').values_list(
                'pk', 'status', 'updated_at',
                'refunded_amount_clp', 'net_amount_clp',
            )),
            before_payments,
        )
        self.assertEqual(Refund.objects.count(), before_refunds)
        self.assertEqual(Settlement.objects.count(), before_settlements)

    def test_cross_module_cancellations_preserve_consolidated_totals(self):
        prof_outcome = self._cancel_professional_36h()
        space_request, created = self._cancel_space_60h()
        self.assertTrue(created)
        self.assertEqual(prof_outcome.refund.amount_clp, 15000)
        self.assertEqual(space_request.refund_amount_clp, 18000)

        self.prof_payment.refresh_from_db()
        self.space_payment.refresh_from_db()
        self.assertEqual(self.prof_payment.net_amount_clp, 4400)
        self.assertEqual(self.space_payment.net_amount_clp, 0)
        self.assertEqual(Refund.objects.filter(status=Refund.Status.PROCESSED).count(), 3)

        self.client.force_login(self.member)
        member_summary = self.client.get(reverse('payments:my_payments')).context
        self.assertEqual(member_summary['approved_total'], 46000)
        self.assertEqual(member_summary['refunded_total'], 41000)
        self.assertEqual(member_summary['retained_total'], 5000)

        self.client.force_login(self.professional)
        pro_summary = self.client.get(reverse('payments:professional_income')).context
        self.assertEqual(pro_summary['refunded_total'], 23000)
        self.assertEqual(pro_summary['to_settle_total'], 4400)

        self.client.force_login(self.provider)
        space_summary = self.client.get(reverse('payments:space_income')).context
        self.assertEqual(space_summary['totals']['refunded_total'], 18000)
        self.assertEqual(space_summary['totals']['net_total'], 0)

        self.client.force_login(self.admin)
        rows = self.client.get(
            reverse('payments:space_settlement_admin'),
        ).context['rows']
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['no_balance'])
        self.assertFalse(rows[0]['can_settle'])

    def test_second_cancellation_never_creates_another_refund(self):
        self._cancel_professional_36h()
        self._cancel_space_60h()
        refunds_before = Refund.objects.count()
        with self.assertRaises(ProfessionalBookingPaymentError):
            self._cancel_professional_36h()
        cancelled_at = self.space_start - timedelta(hours=60)
        with self.assertRaises(SpaceCancellationError):
            with patch('django.utils.timezone.now', return_value=cancelled_at):
                request_paid_space_cancellation(
                    booking_id=self.space_booking.pk,
                    actor=self.member,
                    reason='Segundo intento de cancelar el mismo arriendo.',
                )
        self.assertEqual(Refund.objects.count(), refunds_before)
        self.assertEqual(
            SpaceCancellationRequest.objects.filter(
                booking=self.space_booking,
            ).count(),
            1,
        )

    def test_payment_cannot_point_to_two_independent_origins(self):
        invalid = Payment(
            payer=self.member,
            activity=self.activity,
            professional_booking=self.prof_booking,
            economic_scope=Payment.EconomicScope.PROFESSIONAL_ACTIVITY,
            amount_clp=8000,
        )
        with self.assertRaises(ValidationError):
            invalid.full_clean()

    def test_database_rejects_second_active_space_payment(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Payment.objects.create(
                    payer=self.member,
                    space_booking=self.space_booking,
                    economic_scope=Payment.EconomicScope.SPACE_BOOKING,
                    amount_clp=18000,
                    status=Payment.Status.APPROVED,
                )
        self.assertEqual(
            Payment.objects.filter(
                space_booking=self.space_booking,
                status=Payment.Status.APPROVED,
            ).count(),
            1,
        )
