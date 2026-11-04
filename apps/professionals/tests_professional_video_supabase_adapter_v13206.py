"""Pruebas V132.06.2 del adaptador privado S3, sin acceder a Supabase.

Destino:
apps/professionals/tests_professional_video_supabase_adapter_v13206.py

Ejecutar:
python manage.py test apps.professionals.tests_professional_video_supabase_adapter_v13206 --verbosity 2
"""

import os
import sys

from io import BytesIO
from types import ModuleType
from unittest.mock import Mock, patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from .video_supabase_s3_adapter_v13206 import (
    SupabaseVideoS3Adapter,
)


TEST_ENV = {
    'SUPABASE_VIDEO_S3_BUCKET': 'portafolio-privado',
    'SUPABASE_VIDEO_S3_ENDPOINT': (
        'https://ejemplo.storage.supabase.co/storage/v1/s3'
    ),
    'SUPABASE_VIDEO_S3_REGION': 'us-east-1',
    'SUPABASE_VIDEO_S3_ACCESS_KEY': 'clave-falsa',
    'SUPABASE_VIDEO_S3_SECRET_KEY': 'secreto-falso',
}


KEY_MP4 = (
    'professional_videos/7/'
    + 'a' * 32
    + '.mp4'
)

KEY_WEBM = (
    'professional_videos/7/'
    + 'b' * 32
    + '.webm'
)


class SupabaseVideoS3AdapterTests(SimpleTestCase):

    def setUp(self):
        self.client = Mock()

        self.adapter = SupabaseVideoS3Adapter(
            client=self.client,
            bucket='portafolio-privado',
        )

    def test_new_key_is_unique_private_and_scoped_to_professional(self):
        key_one = self.adapter.new_key(
            professional_profile_id=7,
            extension='.mp4',
        )

        key_two = self.adapter.new_key(
            professional_profile_id=7,
            extension='.mp4',
        )

        self.assertRegex(
            key_one,
            r'^professional_videos/7/[a-f0-9]{32}\.mp4$',
        )

        self.assertNotEqual(key_one, key_two)
        self.assertNotIn('http', key_one)

    def test_new_key_rejects_invalid_profiles_and_extensions(self):

        for invalid_id in (0, -1, '7', True, None):
            with self.subTest(profile=invalid_id):
                with self.assertRaises(ValueError):
                    self.adapter.new_key(
                        professional_profile_id=invalid_id,
                        extension='.mp4',
                    )

        for invalid_extension in (
            '.exe',
            '.mov',
            '',
            '../mp4',
        ):
            with self.subTest(extension=invalid_extension):
                with self.assertRaises(ValueError):
                    self.adapter.new_key(
                        professional_profile_id=7,
                        extension=invalid_extension,
                    )

    def test_bucket_requires_safe_name_and_client(self):

        with self.assertRaises(ValueError):
            SupabaseVideoS3Adapter(
                client=self.client,
                bucket='../otro',
            )

        with self.assertRaises(ValueError):
            SupabaseVideoS3Adapter(
                client=None,
                bucket='portafolio-privado',
            )

    def test_cross_professional_and_unsafe_keys_never_call_s3(self):

        unsafe_keys = (
            KEY_MP4,
            (
                '../professional_videos/8/'
                + 'a' * 32
                + '.mp4'
            ),
            (
                'professional_videos/8/'
                + 'a' * 32
                + '.mp4'
            ),
            (
                'professional_videos/7/../7/'
                + 'a' * 32
                + '.mp4'
            ),
            'professional_videos/7/malicioso.exe',
        )

        for key in unsafe_keys:
            with self.subTest(key=key):

                profile_id = (
                    8 if key == KEY_MP4 else 7
                )

                with self.assertRaises(ValueError):
                    self.adapter.delete(
                        key=key,
                        professional_profile_id=profile_id,
                    )

        self.client.delete_object.assert_not_called()

    def test_upload_mp4_is_private_and_rewinds_file(self):

        fileobj = BytesIO(b'video-simulado')
        fileobj.seek(5)

        result = self.adapter.upload(
            key=KEY_MP4,
            professional_profile_id=7,
            fileobj=fileobj,
        )

        self.assertEqual(result, KEY_MP4)

        self.client.upload_fileobj.assert_called_once_with(
            fileobj,
            'portafolio-privado',
            KEY_MP4,
            ExtraArgs={
                'ContentType': 'video/mp4',
                'ContentDisposition': 'inline',
                'CacheControl': 'private, no-store',
            },
        )

        self.assertEqual(fileobj.tell(), 0)

    def test_upload_webm_sets_correct_content_type(self):

        self.adapter.upload(
            key=KEY_WEBM,
            professional_profile_id=7,
            fileobj=BytesIO(b'webm-simulado'),
        )

        self.assertEqual(
            self.client.upload_fileobj.call_args.kwargs[
                'ExtraArgs'
            ]['ContentType'],
            'video/webm',
        )

    def test_upload_rejects_non_file_object(self):

        with self.assertRaisesRegex(
            ValueError,
            'archivo binario',
        ):
            self.adapter.upload(
                key=KEY_MP4,
                professional_profile_id=7,
                fileobj='video.mp4',
            )

        self.client.upload_fileobj.assert_not_called()

    def test_head_returns_remote_metadata(self):

        self.client.head_object.return_value = {
            'ContentLength': 3456,
            'ContentType': 'video/mp4',
        }

        result = self.adapter.head(
            key=KEY_MP4,
            professional_profile_id=7,
        )

        self.assertEqual(
            result,
            {
                'size_bytes': 3456,
                'content_type': 'video/mp4',
            },
        )

        self.client.head_object.assert_called_once_with(
            Bucket='portafolio-privado',
            Key=KEY_MP4,
        )

    def test_head_rejects_empty_object(self):

        self.client.head_object.return_value = {
            'ContentLength': 0,
        }

        with self.assertRaisesRegex(
            ValueError,
            'tamaño válido',
        ):
            self.adapter.head(
                key=KEY_MP4,
                professional_profile_id=7,
            )

    def test_get_supports_range_without_public_url(self):

        response = {
            'Body': object(),
            'ContentLength': 12,
        }

        self.client.get_object.return_value = response

        self.assertIs(
            self.adapter.get(
                key=KEY_MP4,
                professional_profile_id=7,
            ),
            response,
        )

        self.client.get_object.assert_called_with(
            Bucket='portafolio-privado',
            Key=KEY_MP4,
        )

        self.assertIs(
            self.adapter.get(
                key=KEY_MP4,
                professional_profile_id=7,
                byte_range='bytes=2-8',
            ),
            response,
        )

        self.client.get_object.assert_called_with(
            Bucket='portafolio-privado',
            Key=KEY_MP4,
            Range='bytes=2-8',
        )

    def test_get_rejects_invalid_byte_ranges(self):

        for bad_range in (
            'bytes=-',
            'bytes=abc-2',
            'bytes=1-2,3-4',
            '0-2',
            '',
            'bytes=9-2',
        ):
            with self.subTest(byte_range=bad_range):

                with self.assertRaises(ValueError):
                    self.adapter.get(
                        key=KEY_MP4,
                        professional_profile_id=7,
                        byte_range=bad_range,
                    )

        self.client.get_object.assert_not_called()

    def test_delete_uses_only_valid_scoped_key(self):

        self.adapter.delete(
            key=KEY_MP4,
            professional_profile_id=7,
        )

        self.client.delete_object.assert_called_once_with(
            Bucket='portafolio-privado',
            Key=KEY_MP4,
        )

    @override_settings(
        PROFESSIONAL_VIDEO_STORAGE_MODE='local'
    )
    def test_from_settings_refuses_remote_mode_when_local_is_active(self):

        with self.assertRaisesRegex(
            ImproperlyConfigured,
            'modo|MODE',
        ):
            SupabaseVideoS3Adapter.from_settings()

    @override_settings(
        PROFESSIONAL_VIDEO_STORAGE_MODE='supabase'
    )
    def test_from_settings_constructs_s3_client_without_network(self):

        fake_boto3 = ModuleType('boto3')

        fake_boto3.client = Mock(
            return_value=self.client,
        )

        fake_botocore = ModuleType('botocore')

        fake_config_module = ModuleType(
            'botocore.config'
        )

        fake_config_module.Config = Mock(
            return_value='configuracion-simulada'
        )

        with patch.dict(os.environ, TEST_ENV):

            with patch.dict(
                sys.modules,
                {
                    'boto3': fake_boto3,
                    'botocore': fake_botocore,
                    'botocore.config': fake_config_module,
                },
            ):
                adapter = (
                    SupabaseVideoS3Adapter.from_settings()
                )

        self.assertEqual(
            adapter.bucket,
            'portafolio-privado',
        )

        self.assertIs(
            adapter.client,
            self.client,
        )

        fake_config_module.Config.assert_called_once_with(
            signature_version='s3v4',
            s3={
                'addressing_style': 'path',
            },
        )

        fake_boto3.client.assert_called_once_with(
            's3',
            endpoint_url=TEST_ENV[
                'SUPABASE_VIDEO_S3_ENDPOINT'
            ],
            region_name='us-east-1',
            aws_access_key_id='clave-falsa',
            aws_secret_access_key='secreto-falso',
            config='configuracion-simulada',
        )