"""Destino: apps/professionals/migrations/0009_private_professional_video_v13201.py"""

import apps.professionals.video_models_v13200
import apps.professionals.video_storage_v13201
import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('professionals', '0008_professional_portfolio_video_v13200'),
    ]

    operations = [
        migrations.AlterField(
            model_name='professionalportfoliovideo',
            name='video_file',
            field=models.FileField(
                blank=True,
                max_length=400,
                storage=apps.professionals.video_storage_v13201.PrivatePortfolioStorage(),
                upload_to=apps.professionals.video_models_v13200.professional_portfolio_upload_path,
                validators=[django.core.validators.FileExtensionValidator(['mp4', 'mov', 'webm'])],
            ),
        ),
    ]
