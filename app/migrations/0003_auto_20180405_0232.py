# -*- coding: utf-8 -*-
# Generated by Django 1.11.4 on 2018-04-05 02:32
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0002_auto_20180404_2039'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='peripheralsetupmodel',
            options={'verbose_name': 'Peripheral Setup', 'verbose_name_plural': 'Peripheral Setups'},
        ),
    ]
