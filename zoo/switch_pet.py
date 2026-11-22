"""Commit selection only once the outgoing and target slots are safe."""
from zoo import pet_slots


def activate(cfg, pet, target, defaults, epoch, make_pet, flush_brain=None, root=""):
    """Return (target_state, is_new); leave live dicts untouched on failure.

    The caller validates the target against the installed cast and prepares
    the legacy migration at boot. Global settings are committed last. A
    failed commit may leave a valid new slot or adjust the parked slot's
    timestamp, but never changes which pet is selected or its saved progress.
    """
    current = cfg["personagem"]
    if current == target:
        return dict(pet), False
    if pet_slots.has_pet(target, root):
        incoming = pet_slots.load_pet(target, defaults, root)
        create = False
    else:
        incoming = make_pet()
        create = True
    # Reanchor the incoming clock while the target is still parked. Saving
    # this before config avoids counting parked time after immediate reboot.
    update_incoming = bool(epoch and incoming.get("epoch") != epoch)
    if update_incoming:
        incoming["epoch"] = epoch
    outgoing = dict(pet)
    if epoch:
        outgoing["epoch"] = epoch
    pet_slots.save_pet(current, outgoing, root)
    if flush_brain is not None:
        flush_brain(pet_slots.brain_dir(current, root))
    if create or update_incoming:
        pet_slots.save_pet(target, incoming, root)
    selection = dict(cfg)
    selection["personagem"] = target
    path = (root.rstrip("/") + "/" if root else "") + "config.json"
    pet_slots.save_json(path, selection)
    return incoming, create
