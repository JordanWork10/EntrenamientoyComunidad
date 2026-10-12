from django.db import models


class Region(models.Model):
    """
    Región geográfica utilizada por la plataforma.
    """

    name = models.CharField(
        max_length=150,
        unique=True,
        verbose_name='Nombre'
    )

    code = models.CharField(
        max_length=10,
        unique=True,
        verbose_name='Código'
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name='Activa'
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de creación'
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Última actualización'
    )

    class Meta:
        verbose_name = 'Región'
        verbose_name_plural = 'Regiones'
        ordering = ['name']

    def __str__(self):
        return self.name


class Commune(models.Model):
    """
    Comuna perteneciente a una región.
    """

    region = models.ForeignKey(
        Region,
        on_delete=models.PROTECT,
        related_name='communes',
        verbose_name='Región'
    )

    name = models.CharField(
        max_length=150,
        verbose_name='Nombre'
    )

    code = models.CharField(
        max_length=10,
        unique=True,
        verbose_name='Código'
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name='Activa'
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de creación'
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Última actualización'
    )

    class Meta:
        verbose_name = 'Comuna'
        verbose_name_plural = 'Comunas'
        ordering = ['region__name', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['region', 'name'],
                name='unique_commune_per_region'
            )
        ]

    def __str__(self):
        return f'{self.name} - {self.region.name}'