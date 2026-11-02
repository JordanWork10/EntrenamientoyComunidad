"""V132.00 — destino: apps/professionals/migrations/0008_professional_portfolio_video_v13200.py."""

from django.db import migrations, models
import django.db.models.deletion
import django.core.validators
import apps.professionals.video_models_v13200
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ('professionals', '0007_backfill_availability_history'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProfessionalPortfolioVideo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('public_id', models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ('title', models.CharField(max_length=140)),
                ('description', models.TextField(blank=True, max_length=600)),
                ('category', models.CharField(choices=[
                    ('presentation', 'Presentación profesional'),
                    ('technique', 'Demostración técnica'),
                    ('exercises', 'Ejercicios y movilidad'),
                    ('educational', 'Contenido educativo'),
                    ('other', 'Otro contenido'),
                ], default='presentation', max_length=20)),
                ('status', models.CharField(choices=[
                    ('draft', 'Borrador'),
                    ('processing', 'Procesando'),
                    ('pending_review', 'Pendiente de revisión'),
                    ('approved', 'Publicado'),
                    ('rejected', 'Rechazado'),
                    ('hidden', 'Oculto'),
                ], default='draft', max_length=20)),
                ('video_file', models.FileField(blank=True, max_length=400,
                    upload_to=apps.professionals.video_models_v13200.professional_portfolio_upload_path,
                    validators=[django.core.validators.FileExtensionValidator(['mp4', 'mov', 'webm'])])),
                ('storage_backend', models.CharField(choices=[
                    ('local', 'Almacenamiento de desarrollo'),
                    ('external', 'Proveedor de video externo'),
                ], default='local', max_length=20)),
                ('external_asset_id', models.CharField(blank=True, max_length=160)),
                ('duration_seconds', models.PositiveIntegerField(blank=True, null=True)),
                ('file_size_bytes', models.PositiveBigIntegerField(blank=True, null=True)),
                ('rights_confirmed', models.BooleanField(default=False)),
                ('is_featured', models.BooleanField(default=False)),
                ('display_order', models.PositiveSmallIntegerField(default=0)),
                ('review_notes', models.TextField(blank=True, max_length=1000)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('published_at', models.DateTimeField(blank=True, null=True)),
                ('professional_profile', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='portfolio_videos',
                    to='professionals.professionalprofile',
                )),
            ],
            options={
                'verbose_name': 'Video de portafolio profesional',
                'verbose_name_plural': 'Videos de portafolio profesional',
                'ordering': ['display_order', '-created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='professionalportfoliovideo',
            constraint=models.UniqueConstraint(
                condition=models.Q(is_featured=True, status='approved'),
                fields=('professional_profile',),
                name='one_featured_approved_professional_video',
            ),
        ),
        migrations.AddConstraint(
            model_name='professionalportfoliovideo',
            constraint=models.CheckConstraint(
                condition=(
                    ~models.Q(status='approved') | (
                        models.Q(duration_seconds__gt=0)
                        & models.Q(file_size_bytes__gt=0)
                        & models.Q(rights_confirmed=True)
                    )
                ),
                name='approved_professional_video_has_metadata',
            ),
        ),
    ]
