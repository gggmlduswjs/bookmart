from django.shortcuts import redirect

EXEMPT_PATHS = {'/login/', '/logout/', '/password-change/', '/admin/', '/register/'}
EXEMPT_PREFIXES = ('/admin/', '/invite/', '/s/')


class ForcePasswordChangeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.user.is_authenticated
            and getattr(request.user, 'must_change_password', False)
            and request.path not in EXEMPT_PATHS
            and not any(request.path.startswith(p) for p in EXEMPT_PREFIXES)
        ):
            return redirect('/password-change/')
        return self.get_response(request)
