from django.shortcuts import redirect

EXEMPT_PATHS = {'/login/', '/logout/', '/password-change/', '/admin/'}


class ForcePasswordChangeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.user.is_authenticated
            and getattr(request.user, 'must_change_password', False)
            and request.path not in EXEMPT_PATHS
            and not request.path.startswith('/admin/')
        ):
            return redirect('/password-change/')
        return self.get_response(request)
