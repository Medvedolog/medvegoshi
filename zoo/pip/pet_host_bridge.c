/* Host-only opaque C ABI over the unmodified MIT Pip-KeyPet pet core.
 * See ../upstream/pip/LICENSE and ../UPSTREAM.md. No ESP32 I/O or saves here.
 */
#include "pet.h"
#include "moods.h"

#include <math.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

#define MAX_TIME INT64_C(4102444800)
_Static_assert(sizeof(bool) == 1, "host snapshot expects one byte per bool");
_Static_assert(PIP_MOOD_COUNT < INT8_MAX, "Pip mood IDs must fit pet_t");

const char *pip_host_mood_name(int mood)
{
#define MOOD(key, name) [PIP_##key] = name
    static const char *const names[PIP_MOOD_COUNT] = {
        MOOD(NEUTRAL, "neutral"), MOOD(HAPPY, "happy"), MOOD(SAD, "sad"),
        MOOD(ANGRY, "angry"), MOOD(SURPRISED, "surprised"), MOOD(SLEEPY, "sleepy"),
        MOOD(ASLEEP, "asleep"), MOOD(SKEPTICAL, "skeptical"), MOOD(CURIOUS, "curious"),
        MOOD(LOVE, "love"), MOOD(DIZZY, "dizzy"), MOOD(OUCH, "ouch"),
        MOOD(STONED, "stoned"), MOOD(PINKEYE, "pinkeye"), MOOD(NAUSEOUS, "nauseous"),
        MOOD(SICK, "sick"), MOOD(TIRED, "tired"), MOOD(EXHAUSTED, "exhausted"),
        MOOD(ANNOYED, "annoyed"), MOOD(FURIOUS, "furious"), MOOD(RAGE, "rage"),
        MOOD(SWEARING, "swearing"), MOOD(INDIGNANT, "indignant"), MOOD(BELLIGERENT, "belligerent"),
        MOOD(HURT, "hurt"), MOOD(DISGUSTED, "disgusted"), MOOD(SUSPICIOUS, "suspicious"),
        MOOD(CYNICAL, "cynical"), MOOD(AFRAID, "afraid"), MOOD(NERVOUS, "nervous"),
        MOOD(DESPONDENT, "despondent"), MOOD(LONELY, "lonely"), MOOD(GLOOMY, "gloomy"),
        MOOD(DULL, "dull"), MOOD(SHY, "shy"), MOOD(SMUG, "smug"), MOOD(BORED, "bored"),
        MOOD(SHOCKED, "shocked"), MOOD(DISMAYED, "dismayed"), MOOD(PUZZLED, "puzzled"),
        MOOD(AMAZED, "amazed"), MOOD(CHEEKY, "cheeky"), MOOD(CONTENT, "content"),
        MOOD(COMFY, "comfy"), MOOD(YES, "yes"), MOOD(NO, "no"),
    };
#undef MOOD
    return mood >= 0 && mood < PIP_MOOD_COUNT ? names[mood] : NULL;
}

static int valid_clock(int64_t now, int tz_min)
{
    return now >= 0 && now <= MAX_TIME && tz_min >= -840 && tz_min <= 840 &&
           now + (int64_t)tz_min * 60 >= 0;
}

pet_t *pip_host_new(uint32_t seed, int64_t now, int tz_min)
{
    if (!valid_clock(now, tz_min)) return NULL;
    pet_t *p = malloc(sizeof *p);
    if (p) {
        pet_init(p, now, tz_min, seed);
        pet_settle(p, tz_min);
    }
    return p;
}

void pip_host_free(pet_t *p) { free(p); }

int pip_host_update(pet_t *p, int64_t now, int tz_min)
{
    if (!valid_clock(now, tz_min) || now < p->last) return 0;
    pet_update(p, now, tz_min);
    pet_settle(p, tz_min);
    return 1;
}

int pip_host_event(pet_t *p, const char *name, int tz_min)
{
    static const char *const names[] = {
        [PET_FEED] = "feed", [PET_PLAY] = "play", [PET_STROKE] = "stroke",
        [PET_POKE] = "poke", [PET_STEP] = "step", [PET_SHAKE] = "shake",
        [PET_WAKE] = "wake", [PET_SLEEP] = "sleep", [PET_SEEN] = "seen",
        [PET_WIN] = "win", [PET_LOSE] = "lose", [PET_RECORD] = "record",
        [PET_FRIGHT] = "fright", [PET_FLOOD] = "flood", [PET_FED_UP] = "fed_up",
    };
    for (size_t i = 0; i < sizeof names / sizeof names[0]; i++) {
        if (names[i] && !strcmp(names[i], name)) {
            if (i == PET_STEP && p->steps_today == INT32_MAX) return -2;
            int reaction = pet_event(p, (int)i);
            pet_settle(p, tz_min);
            return reaction;
        }
    }
    return -2;
}

/* Integer and float arrays are an explicit host API, not an ABI image of pet_t. */
void pip_host_observe(const pet_t *p, int tz_min, int32_t out[5],
                      float values[7], int64_t *now)
{
    pet_why_t why;
    int mood = pet_mood_why(p, tz_min, &why);
    out[0] = mood; out[1] = why.kind; out[2] = why.which;
    out[3] = why.hold; out[4] = p->asleep;
    values[0] = p->food; values[1] = p->energy; values[2] = p->fun;
    values[3] = p->love; values[4] = p->walk;
    values[5] = pet_valence(p); values[6] = why.value;
    *now = p->last;
}

size_t pip_host_state_size(void) { return sizeof(pet_t); }

uint64_t pip_host_layout(void)
{
#define FIELD(n) offsetof(pet_t, n), sizeof(((pet_t *)0)->n)
    static const size_t layout[] = {
        sizeof(pet_t), PET_VERSION, FIELD(version), FIELD(last), FIELD(up_until),
        FIELD(food), FIELD(energy), FIELD(fun), FIELD(love), FIELD(walk), FIELD(day_mood),
        FIELD(annoy), FIELD(day), FIELD(steps_today), FIELD(rng), FIELD(asleep),
        FIELD(bedded), FIELD(charging), FIELD(bat), FIELD(after_mood), FIELD(after_why),
        FIELD(rare_mood), FIELD(pool), FIELD(hold), FIELD(cur), FIELD(prev), FIELD(slot),
        FIELD(day_base), FIELD(stride), FIELD(unseen), FIELD(after_until), FIELD(rare_at),
        FIELD(hold_since), FIELD(charge_since), FIELD(woke_at), FIELD(stuffed_at),
    };
#undef FIELD
    uint64_t hash = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < sizeof layout / sizeof layout[0]; i++) {
        hash ^= (uint64_t)layout[i];
        hash *= UINT64_C(1099511628211);
    }
    return hash;
}

void pip_host_snapshot(const pet_t *p, unsigned char *out)
{
    memcpy(out, p, sizeof *p);
}

static int between(float v, float lo, float hi)
{
    return isfinite(v) && v >= lo && v <= hi;
}

static int mood_or_unset(int mood)
{
    return mood == -1 || (mood >= 0 && mood < PIP_MOOD_COUNT);
}

static int plausible_future(int64_t v)
{
    return v >= 0 && v <= MAX_TIME + 86400;
}

static int valid_state(const pet_t *p, int tz_min)
{
    if (p->version != PET_VERSION || !valid_clock(p->last, tz_min) ||
        !plausible_future(p->up_until) || !plausible_future(p->after_until) ||
        !plausible_future(p->rare_at) || p->hold_since < 0 || p->hold_since > p->last ||
        p->charge_since < 0 || p->charge_since > p->last || p->woke_at < 0 ||
        p->woke_at > p->last || p->stuffed_at < 0 || p->stuffed_at > p->last) return 0;
    if (!between(p->food, 0, 1) || !between(p->energy, 0, 1) || !between(p->fun, 0, 1) ||
        !between(p->love, 0, 1) || !between(p->walk, 0, 1) || !between(p->day_mood, -1, 1) ||
        !between(p->day_base, -1, 1) || !between(p->stride, 0, 100) ||
        !isfinite(p->annoy) || p->annoy < 0 || !isfinite(p->unseen) || p->unseen < 0) return 0;
    if (p->day < 0 || p->day > (MAX_TIME + 86400) / 86400 ||
        p->slot < 0 || p->slot > MAX_TIME / 300 || p->steps_today < 0 || !p->rng ||
        (p->bedded && !p->asleep) || p->bat < -1 || p->bat > 100 ||
        !mood_or_unset(p->after_mood) || p->after_why < 0 || p->after_why > PET_AFTER_FED_UP ||
        (p->rare_mood != -1 && p->rare_mood != PIP_STONED && p->rare_mood != PIP_PINKEYE) ||
        p->pool < -1 || p->pool > 3 || p->hold < -1 || p->hold > PET_WHY_URGE * 16 + 15 ||
        !mood_or_unset(p->cur) || !mood_or_unset(p->prev)) return 0;
    return 1;
}

int pip_host_restore(pet_t *p, const unsigned char *raw, size_t count, int tz_min)
{
    if (count != sizeof *p || raw[offsetof(pet_t, asleep)] > 1 ||
        raw[offsetof(pet_t, bedded)] > 1 || raw[offsetof(pet_t, charging)] > 1) return 0;
    pet_t candidate;
    memcpy(&candidate, raw, sizeof candidate);
    if (!valid_state(&candidate, tz_min)) return 0;
    memcpy(p, raw, sizeof *p);
    return 1;
}
