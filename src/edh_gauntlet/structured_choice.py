"""Shared ingress for structured combat responses across console, host and replay."""
TYPES=frozenset({'block_declaration','combat_damage'})


def module(request):
    from . import block_declaration,combat_damage
    return {'block_declaration':block_declaration,'combat_damage':combat_damage}[request['response_type']]


def validate(request,value):return module(request).validate(request,value)


def presentation(request):return module(request).presentation(request)
