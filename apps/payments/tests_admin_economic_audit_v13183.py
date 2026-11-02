"""V131.83 — pruebas de la auditoría económica de solo lectura.

Copiar como: apps/payments/tests_admin_economic_audit_v13183.py

Ejecutar:
python manage.py test apps.payments.tests_admin_economic_audit_v13183 --verbosity 2
"""

from datetime import time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import resolve, reverse
from django.utils import timezone

from apps.bookings.models import Booking
from apps.bookings.services import create_booking
from apps.professionals.models import (
    ProfessionalCategory,
    ProfessionalProfile,
    ProfessionalService,
    ProfessionalServiceAvailability,
    ProfessionalSpecialty,
)

from .admin_economic_audit_v13183 import (
    _parse_date,
    admin_economic_audit,
)
from .models import Payment, Refund, Settlement


class EconomicAuditValidationTests(SimpleTestCase):

    def test_route_points_to_read_only_view(self):
        path = reverse('payments:admin_economic_audit')

        self.assertEqual(
            resolve(path).func,
            admin_economic_audit,
        )

    def test_invalid_date_is_rejected(self):
        self.assertIsNone(_parse_date('2026-02-30'))
        self.assertIsNone(_parse_date('fecha'))
        self.assertIsNone(_parse_date(''))

    def test_non_staff_is_forbidden_before_query(self):
        request = RequestFactory().get(
            reverse('payments:admin_economic_audit')
        )

        request.user = get_user_model()(
            username='no_admin_13183',
            is_staff=False,
        )

        with self.assertRaises(PermissionDenied):
            admin_economic_audit(request)

    def test_post_is_disallowed(self):
        request = RequestFactory().post(
            reverse('payments:admin_economic_audit')
        )

        request.user = get_user_model()(
            username='staff_13183',
            is_staff=True,
        )

        self.assertEqual(
            admin_economic_audit(request).status_code,
            405,
        )


class EconomicAuditDatabaseTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()

        # Administrador principal.
        cls.admin = User.objects.create_superuser(
            username='admin_13183',
            email='admin_13183@example.test',
            password='test-pass',
        )

        # V131.83 CORRECCIÓN:
        # Todos los usuarios deben tener correos únicos.
        # El modelo accounts.User no permite emails duplicados,
        # incluyendo cadenas vacías.

        cls.staff_without_permissions = User.objects.create_user(
            username='unprivileged_staff_13183',
            email='unprivileged_staff_13183@example.test',
            password='test-pass',
            is_staff=True,
        )

        cls.auditor = User.objects.create_user(
            username='auditor_13183',
            email='auditor_13183@example.test',
            password='test-pass',
            is_staff=True,
        )

        # Permisos de lectura específicos.
        for model_name in ('payment', 'refund', 'settlement'):
            cls.auditor.user_permissions.add(
                Permission.objects.get(
                    content_type__app_label='payments',
                    content_type__model=model_name,
                    codename=f'view_{model_name}',
                )
            )

        # Miembro de prueba.
        cls.member = User.objects.create_user(
            username='member_13183',
            email='member_13183@example.test',
            password='test-pass',
        )

        # Profesional de prueba.
        cls.professional = User.objects.create_user(
            username='professional_13183',
            email='professional_13183@example.test',
            password='test-pass',
        )

        # Categoría profesional.
        category = ProfessionalCategory.objects.create(
            name='Categoría V13183',
            slug='categoria-v13183',
        )

        # Especialidad profesional.
        specialty = ProfessionalSpecialty.objects.create(
            name='Especialidad V13183',
            slug='especialidad-v13183',
            category=category,
        )

        # Perfil profesional.
        profile = ProfessionalProfile.objects.create(
            user=cls.professional,
            category=category,
            specialty=specialty,
            bio='Profesional para auditoría.',
            offers_online=True,
            verification_status=(
                ProfessionalProfile.VerificationStatus.VERIFIED
            ),
            is_public=True,
        )

        # Servicio individual.
        service = ProfessionalService.objects.create(
            professional_profile=profile,
            name='Sesión auditada V13183',
            description='Sesión de prueba.',
            mode=ProfessionalService.ServiceMode.ONLINE,
            duration_minutes=60,
            price=20000,
            publication_status=(
                ProfessionalService.PublicationStatus.PUBLISHED
            ),
        )

        # Disponibilidad del servicio.
        cls.day = timezone.localdate() + timedelta(days=10)

        ProfessionalServiceAvailability.objects.create(
            service=service,
            weekday=cls.day.weekday(),
            start_time=time(9),
            end_time=time(14),
            valid_from=cls.day,
            is_active=True,
        )

        # Reserva de sesión individual.
        cls.booking = create_booking(
            user=cls.member,
            service=service,
            session_date=cls.day,
            start_time=time(9),
            end_time=time(10),
        )

        cls.booking.status = Booking.Status.CONFIRMED
        cls.booking.confirmed_at = timezone.now()

        cls.booking.save(
            update_fields=[
                'status',
                'confirmed_at',
                'updated_at',
            ]
        )

        # Liquidación económica de prueba.
        cls.settlement = Settlement.objects.create(
            beneficiary=cls.professional,
            scope_type=Settlement.ScopeType.PROFESSIONAL_DAY,
            reference_date=cls.day,
            gross_amount_clp=20000,
            refunded_amount_clp=15000,
            commission_base_clp=5000,
            commission_amount_clp=600,
            net_amount_clp=4400,
            status=Settlement.Status.PENDING,
        )

        # Pago con reembolso parcial.
        cls.payment = Payment.objects.create(
            payer=cls.member,
            professional_booking=cls.booking,
            economic_scope=(
                Payment.EconomicScope.PROFESSIONAL_SERVICE
            ),
            amount_clp=20000,
            refunded_amount_clp=15000,
            commission_base_clp=5000,
            commission_amount_clp=600,
            net_amount_clp=4400,
            status=Payment.Status.PARTIALLY_REFUNDED,
            settlement=cls.settlement,
            provider_reference='SANDBOX-AUDIT-83',
        )

        # Reembolso del 75 %.
        cls.refund = Refund.objects.create(
            payment=cls.payment,
            requested_by=cls.member,
            refund_type=Refund.RefundType.PARTIAL,
            reason=Refund.Reason.MEMBER_CANCELLATION,
            amount_clp=15000,
            status=Refund.Status.PROCESSED,
            policy_percentage_snapshot=Decimal('75.00'),
            policy_version_snapshot='PAYMENTS_POLICY_V1',
            processed_at=timezone.now(),
        )

        cls.url = reverse('payments:admin_economic_audit')

    def setUp(self):
        self.client.force_login(self.admin)

    # ---------------------------------------------------------
    # PRUEBAS DE SEGURIDAD
    # ---------------------------------------------------------

    def test_non_authenticated_user_must_log_in(self):
        self.client.logout()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn('next=', response.url)

    def test_staff_without_all_three_read_permissions_gets_403(self):
        self.client.force_login(
            self.staff_without_permissions
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_staff_with_three_read_permissions_can_audit(self):
        self.client.force_login(self.auditor)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

    # ---------------------------------------------------------
    # PRUEBAS DE HISTORIAL ECONÓMICO
    # ---------------------------------------------------------

    def test_payment_history_preserves_gross_refund_commission_net(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            response.context['gross_total'],
            20000,
        )

        self.assertEqual(
            response.context['refunded_total'],
            15000,
        )

        self.assertEqual(
            response.context['net_total'],
            4400,
        )

        self.assertContains(
            response,
            str(self.payment.public_id),
        )

        self.assertContains(
            response,
            'SANDBOX-AUDIT-83',
        )

    def test_refund_tab_shows_policy_and_payment_uuid(self):
        response = self.client.get(
            self.url,
            {'tipo': 'reembolsos'},
        )

        self.assertEqual(
            response.context['page_obj'].paginator.count,
            1,
        )

        self.assertContains(
            response,
            str(self.refund.public_id),
        )

        self.assertContains(
            response,
            str(self.payment.public_id),
        )

        self.assertContains(
            response,
            'PAYMENTS_POLICY_V1',
        )

    # ---------------------------------------------------------
    # PRUEBAS DE BÚSQUEDA
    # ---------------------------------------------------------

    def test_search_refund_by_related_payment_uuid(self):
        response = self.client.get(
            self.url,
            {
                'tipo': 'reembolsos',
                'buscar': str(self.payment.public_id),
            },
        )

        self.assertEqual(
            response.context['page_obj'].paginator.count,
            1,
        )

    def test_search_settlement_by_related_payment_uuid(self):
        response = self.client.get(
            self.url,
            {
                'tipo': 'liquidaciones',
                'buscar': str(self.payment.public_id),
            },
        )

        self.assertEqual(
            response.context['page_obj'].paginator.count,
            1,
        )

        self.assertContains(
            response,
            str(self.settlement.public_id),
        )

    # ---------------------------------------------------------
    # PRUEBAS DE FILTROS
    # ---------------------------------------------------------

    def test_origin_filter_keeps_only_matching_payments(self):
        sessions = self.client.get(
            self.url,
            {'origen': 'sesiones'},
        )

        self.assertEqual(
            sessions.context['page_obj'].paginator.count,
            1,
        )

        activities = self.client.get(
            self.url,
            {'origen': 'actividades'},
        )

        self.assertEqual(
            activities.context['page_obj'].paginator.count,
            0,
        )

        spaces = self.client.get(
            self.url,
            {'origen': 'espacios'},
        )

        self.assertEqual(
            spaces.context['page_obj'].paginator.count,
            0,
        )

    def test_origin_filter_applies_to_settlement_scope(self):
        sessions = self.client.get(
            self.url,
            {
                'tipo': 'liquidaciones',
                'origen': 'sesiones',
            },
        )

        spaces = self.client.get(
            self.url,
            {
                'tipo': 'liquidaciones',
                'origen': 'espacios',
            },
        )

        self.assertEqual(
            sessions.context['page_obj'].paginator.count,
            1,
        )

        self.assertEqual(
            spaces.context['page_obj'].paginator.count,
            0,
        )

    def test_status_filter_is_per_record_kind(self):
        response = self.client.get(
            self.url,
            {
                'tipo': 'pagos',
                'estado': Payment.Status.APPROVED,
            },
        )

        self.assertEqual(
            response.context['page_obj'].paginator.count,
            0,
        )

        response = self.client.get(
            self.url,
            {
                'tipo': 'reembolsos',
                'estado': Refund.Status.PROCESSED,
            },
        )

        self.assertEqual(
            response.context['page_obj'].paginator.count,
            1,
        )

    def test_invalid_date_does_not_broaden_query(self):
        invalid = self.client.get(
            self.url,
            {'desde': '2026-99-99'},
        )

        self.assertTrue(
            invalid.context['invalid_dates']
        )

        self.assertEqual(
            invalid.context['page_obj'].paginator.count,
            0,
        )

        inverted = self.client.get(
            self.url,
            {
                'desde': '2026-12-20',
                'hasta': '2026-11-01',
            },
        )

        self.assertTrue(
            inverted.context['invalid_dates']
        )

        self.assertEqual(
            inverted.context['page_obj'].paginator.count,
            0,
        )

    def test_invalid_kind_origin_status_are_ignored(self):
        response = self.client.get(
            self.url,
            {
                'tipo': 'sorpresa',
                'origen': 'campo_invalido',
                'estado': '__all__',
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            response.context['kind'],
            'pagos',
        )

        self.assertEqual(
            response.context['origin'],
            'todos',
        )

        self.assertEqual(
            response.context['selected_status'],
            '',
        )

    # ---------------------------------------------------------
    # PRUEBA DE PAGINACIÓN
    # ---------------------------------------------------------

    def test_pagination_is_bounded_and_keeps_all_records(self):
        for index in range(21):
            Payment.objects.create(
                payer=self.member,
                professional_booking=self.booking,
                economic_scope=(
                    Payment.EconomicScope.PROFESSIONAL_SERVICE
                ),
                amount_clp=20000,
                status=Payment.Status.PENDING,
                provider_reference=f'RETRY-{index}',
            )

        first = self.client.get(self.url)

        second = self.client.get(
            self.url,
            {'pagina': '2'},
        )

        self.assertEqual(
            first.context['page_obj'].paginator.count,
            22,
        )

        self.assertEqual(
            len(first.context['page_obj']),
            20,
        )

        self.assertEqual(
            len(second.context['page_obj']),
            2,
        )

        # Los pagos pendientes no cuentan como ingresos aprobados.
        self.assertEqual(
            first.context['gross_total'],
            20000,
        )

    # ---------------------------------------------------------
    # PRUEBA DE INTEGRIDAD DE LOS DATOS
    # ---------------------------------------------------------

    def test_get_does_not_modify_economic_snapshots(self):
        original_payment_updated = self.payment.updated_at
        original_refund_updated = self.refund.updated_at
        original_settlement_updated = self.settlement.updated_at

        for kind in (
            'pagos',
            'reembolsos',
            'liquidaciones',
        ):
            response = self.client.get(
                self.url,
                {'tipo': kind},
            )

            self.assertEqual(
                response.status_code,
                200,
            )

        self.payment.refresh_from_db()
        self.refund.refresh_from_db()
        self.settlement.refresh_from_db()

        self.assertEqual(
            self.payment.updated_at,
            original_payment_updated,
        )

        self.assertEqual(
            self.refund.updated_at,
            original_refund_updated,
        )

        self.assertEqual(
            self.settlement.updated_at,
            original_settlement_updated,
        )