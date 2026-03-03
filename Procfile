web: python manage.py collectstatic --noinput && python manage.py migrate --noinput && gunicorn config.wsgi:application --workers 2 --timeout 120
