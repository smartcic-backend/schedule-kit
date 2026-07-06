from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('example', '0002_rename_title_alertruletask_name_and_more'),
    ]

    operations = [
        migrations.RenameField(
            model_name='alertruletask',
            old_name='enable',
            new_name='enabled',
        ),
        migrations.RenameField(
            model_name='asyncalertruletask',
            old_name='enable',
            new_name='enabled',
        ),
    ]
