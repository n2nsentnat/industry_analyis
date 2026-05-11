"""
Company analysis bounded context.

Layers (onion, inside → out):
- ``domain``: entities and domain logic
- ``application``: ports, DTOs, orchestrators
- ``infrastructure``: adapters (Adzuna, disk JSON, OpenAI, config)
- ``presentation``: CLI / composition
"""
