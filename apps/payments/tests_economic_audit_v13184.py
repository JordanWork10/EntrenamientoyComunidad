"""V131.84 — pruebas de auditoría transaccional en PostgreSQL.

Copiar como: apps/payments/tests_economic_audit_v13184.py

Ejecutar:
python manage.py test apps.payments.tests_economic_audit_v13184 --verbosity 2
"""

import unittest
from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.bookings.services import create_booking
from apps.professionals.models import (
    ProfessionalCategory,
    ProfessionalProfile,
    ProfessionalService,
    ProfessionalServiceAvailability,
    ProfessionalSpecialty,
)

from .economic_audit_models_v13184 import EconomicAuditEvent
from .models import Payment, Refund, Settlement


@unittest.skipUnless(
    connection.vendor == 'postgresql',
    'Los triggers de V131.84 requieren PostgreSQL.',
)
class EconomicAuditV13184Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser(
            username='audit_admin_13184',
            email='audit_admin_13184@example.test',
            password='test-pass',
        )
        cls.member = User.objects.create_user(
            username='audit_member_13184',
            email='audit_member_13184@example.test',
            password='test-pass',
        )
        cls.staff = User.objects.create_user(
            username='audit_staff_13184',
            email='audit_staff_13184@example.test',
            password='test-pass',
            is_staff=True,
        )
        cls.reader = User.objects.create_user(
            username='audit_reader_13184',
            email='audit_reader_13184@example.test',
            password='test-pass',
            is_staff=True,
        )
        cls.professional = User.objects.create_user(
            username='audit_professional_13184',
            email='audit_professional_13184@example.test',
            password='test-pass',
        )
        for name in ('payment', 'refund', 'settlement'):
            cls.reader.user_permissions.add(Permission.objects.get(
                content_type__app_label='payments',
                content_type__model=name,
                codename=f'view_{name}',
            ))
        cls.day = date(2026, 11, 1)
        cls.settlement = Settlement.objects.create(
            beneficiary=cls.member,
            scope_type=Settlement.ScopeType.PROFESSIONAL_DAY,
            reference_date=cls.day,
            gross_amount_clp=20000,
            refunded_amount_clp=0,
            commission_base_clp=20000,
            commission_amount_clp=2400,
            net_amount_clp=17600,
            status=Settlement.Status.PENDING,
        )

        category = ProfessionalCategory.objects.create(
            name='Categoría auditoría 13184', slug='categoria-audit-13184',
        )
        specialty = ProfessionalSpecialty.objects.create(
            name='Especialidad auditoría 13184',
            slug='especialidad-audit-13184',
            category=category,
        )
        profile = ProfessionalProfile.objects.create(
            user=cls.professional,
            category=category,
            specialty=specialty,
            bio='Profesional de prueba para eventos.',
            offers_online=True,
            verification_status=ProfessionalProfile.VerificationStatus.VERIFIED,
            is_public=True,
        )
        service = ProfessionalService.objects.create(
            professional_profile=profile,
            name='Servicio económico auditado V13184',
            description='Sesión de auditoría.',
            mode=ProfessionalService.ServiceMode.ONLINE,
            duration_minutes=60,
            price=20000,
            publication_status=ProfessionalService.PublicationStatus.PUBLISHED,
        )
        booking_day = timezone.localdate() + timedelta(days=12)
        ProfessionalServiceAvailability.objects.create(
            service=service,
            weekday=booking_day.weekday(),
            start_time=time(9),
            end_time=time(14),
            valid_from=booking_day,
            is_active=True,
        )
        booking = create_booking(
            user=cls.member,
            service=service,
            session_date=booking_day,
            start_time=time(9),
            end_time=time(10),
        )
        cls.payment = Payment.objects.create(
            payer=cls.member,
            professional_booking=booking,
            economic_scope=Payment.EconomicScope.PROFESSIONAL_SERVICE,
            amount_clp=20000,
            commission_base_clp=20000,
            commission_amount_clp=2400,
            net_amount_clp=17600,
            status=Payment.Status.APPROVED,
        )
        cls.refund = Refund.objects.create(
            payment=cls.payment,
            requested_by=cls.member,
            refund_type=Refund.RefundType.PARTIAL,
            reason=Refund.Reason.MEMBER_CANCELLATION,
            amount_clp=15000,
            status=Refund.Status.REQUESTED,
        )
        cls.url = reverse('payments:economic_audit_events')

    def setUp(self):
        self.client.force_login(self.admin)

    def _events(self):
        return EconomicAuditEvent.objects.filter(
            source_type=EconomicAuditEvent.Source.SETTLEMENT,
            source_public_id=self.settlement.public_id,
        )

    def test_creating_settlement_writes_one_event(self):
        self.assertEqual(self._events().count(), 1)
        event = self._events().get()
        self.assertEqual(event.action, EconomicAuditEvent.Action.CREATED)
        self.assertEqual(event.before_state, {})
        self.assertEqual(event.after_state['gross_amount_clp'], 20000)

    def test_creating_payment_is_audited(self):
        events = EconomicAuditEvent.objects.filter(
            source_type=EconomicAuditEvent.Source.PAYMENT,
            source_public_id=self.payment.public_id,
        )
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.get().after_state['status'], 'approved')

    def test_creating_refund_records_the_known_requester(self):
        events = EconomicAuditEvent.objects.filter(
            source_type=EconomicAuditEvent.Source.REFUND,
            source_public_id=self.refund.public_id,
        )
        self.assertEqual(events.count(), 1)
        event = events.get()
        self.assertEqual(event.actor_identifier, str(self.member.pk))
        self.assertEqual(event.actor_source, 'solicitante')

    def test_queryset_payment_update_is_audited(self):
        Payment.objects.filter(pk=self.payment.pk).update(
            status=Payment.Status.PARTIALLY_REFUNDED,
            refunded_amount_clp=15000,
            commission_base_clp=5000,
            commission_amount_clp=600,
            net_amount_clp=4400,
        )
        events = EconomicAuditEvent.objects.filter(
            source_type=EconomicAuditEvent.Source.PAYMENT,
            source_public_id=self.payment.public_id,
        )
        self.assertEqual(events.count(), 2)
        self.assertIn('refunded_amount_clp', events.first().changed_fields)

    def test_queryset_refund_update_is_audited(self):
        Refund.objects.filter(pk=self.refund.pk).update(
            status=Refund.Status.PROCESSED,
            processed_at=timezone.now(),
        )
        events = EconomicAuditEvent.objects.filter(
            source_type=EconomicAuditEvent.Source.REFUND,
            source_public_id=self.refund.public_id,
        )
        self.assertEqual(events.count(), 2)
        self.assertEqual(events.first().after_state['status'], 'processed')

    def test_save_modified_economic_field_is_logged(self):
        self.settlement.status = Settlement.Status.ON_HOLD
        self.settlement.hold_reason = 'Incidencia abierta de prueba'
        self.settlement.save(update_fields=['status', 'hold_reason', 'updated_at'])
        self.assertEqual(self._events().count(), 2)
        change = self._events().first()
        self.assertEqual(change.action, EconomicAuditEvent.Action.UPDATED)
        self.assertEqual(change.before_state['status'], 'pending')
        self.assertEqual(change.after_state['status'], 'on_hold')
        self.assertIn('status', change.changed_fields)
        self.assertIn('hold_reason', change.changed_fields)

    def test_timestamp_only_save_does_not_make_fake_event(self):
        self.settlement.save(update_fields=['updated_at'])
        self.assertEqual(self._events().count(), 1)

    def test_queryset_update_is_also_audited(self):
        Settlement.objects.filter(pk=self.settlement.pk).update(
            status=Settlement.Status.ELIGIBLE,
        )
        self.assertEqual(self._events().count(), 2)
        self.assertEqual(self._events().first().after_state['status'], 'eligible')

    def test_audited_change_rolls_back_with_transaction(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                Settlement.objects.filter(pk=self.settlement.pk).update(
                    status=Settlement.Status.ON_HOLD,
                )
                raise RuntimeError('Simulación de una operación revertida')
        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, Settlement.Status.PENDING)
        self.assertEqual(self._events().count(), 1)

    def test_authorizer_of_settlement_is_recorded_when_known(self):
        Settlement.objects.filter(pk=self.settlement.pk).update(
            status=Settlement.Status.SETTLED,
            settled_by=self.admin,
        )
        event = self._events().first()
        self.assertEqual(event.actor_identifier, str(self.admin.pk))
        self.assertEqual(event.actor_source, 'autorizador')

    def test_creation_does_not_guess_the_operator(self):
        event = self._events().get()
        self.assertEqual(event.actor_identifier, '')
        self.assertEqual(event.actor_source, '')

    def test_cannot_update_event_using_model(self):
        event = self._events().first()
        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError):
            EconomicAuditEvent.objects.filter(pk=event.pk).update(
                action=EconomicAuditEvent.Action.DELETED,
            )

    def test_database_blocks_raw_update_of_event(self):
        event = self._events().first()
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        'UPDATE payments_economic_audit_event '
                        'SET action = %s WHERE id = %s',
                        ['updated', event.pk],
                    )
        self.assertEqual(self._events().count(), 1)

    def test_database_blocks_raw_delete_of_event(self):
        event = self._events().first()
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        'DELETE FROM payments_economic_audit_event WHERE id = %s',
                        [event.pk],
                    )
        self.assertEqual(self._events().count(), 1)

    def test_non_authenticated_user_redirects(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_nonstaff_and_staff_without_permissions_forbidden(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_staff_with_three_view_permissions_allowed(self):
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_post_is_not_allowed(self):
        self.assertEqual(self.client.post(self.url).status_code, 405)

    def test_filter_exact_uuid_finds_only_one_source(self):
        response = self.client.get(self.url, {
            'origen': 'settlement',
            'accion': 'created',
            'id': str(self.settlement.public_id),
        })
        self.assertEqual(response.context['page_obj'].paginator.count, 1)
        self.assertContains(response, str(self.settlement.public_id))

    def test_invalid_uuid_does_not_show_everything(self):
        response = self.client.get(self.url, {'id': 'no-es-uuid'})
        self.assertTrue(response.context['invalid_id'])
        self.assertEqual(response.context['page_obj'].paginator.count, 0)

    def test_get_does_not_create_any_event(self):
        before = EconomicAuditEvent.objects.count()
        for source in ('todos', 'payment', 'refund', 'settlement'):
            self.assertEqual(self.client.get(self.url, {
                'origen': source,
            }).status_code, 200)
        self.assertEqual(EconomicAuditEvent.objects.count(), before)

    def test_pagination_limits_rows_without_losing_events(self):
        for index in range(29):
            Settlement.objects.create(
                beneficiary=self.member,
                scope_type=Settlement.ScopeType.PROFESSIONAL_DAY,
                reference_date=self.day + timedelta(days=index + 1),
                status=Settlement.Status.PENDING,
            )
        first = self.client.get(self.url)
        second = self.client.get(self.url, {'pagina': '2'})
        self.assertEqual(first.context['page_obj'].paginator.count, 32)
        self.assertEqual(len(first.context['page_obj']), 25)
        self.assertEqual(len(second.context['page_obj']), 7)
