/* Experimental MicroPython adapter to the vendored MIT Pip-KeyPet C core.
 * The core authorship and license are in zoo/upstream/pip/LICENSE.
 * This module owns one in-memory pet; it performs no file or hardware I/O.
 */
#include "py/binary.h"
#include "py/obj.h"
#include "py/runtime.h"

#include <limits.h>
#include <stdint.h>
#include <string.h>

#include "pet.h"
#include "moods.h"
#include "voice.h"
#include "eyes_tile.h"

/* Reuse the pure-C named event/status/state validation shared with host QA.
 * No host Python, ctypes, file I/O, or host snapshot format is linked here.
 */
const char *pip_host_mood_name(int mood);
int pip_host_update(pet_t *p, int64_t now, int tz_min);
int pip_host_event(pet_t *p, const char *name, int tz_min);
void pip_host_observe(const pet_t *p, int tz_min, int32_t out[5],
                      float values[7], int64_t *now);
uint64_t pip_host_layout(void);
int pip_host_restore(pet_t *p, const unsigned char *raw, size_t size, int tz_min);

#define MAX_UNIX INT64_C(4102444800)
#define MAX_TZ 840
#define STATE_HEAD 26
#define STATE_FMT 1
#define VOICE_MAX_BYTES 2048
#define VOICE_BLOCK 128
/* "Pip native" wire namespace. State assumes unchanged MIT engine revision. */
#define VENDOR_TAG UINT32_C(0xb505d939)

static pet_t active;
static int tz_minutes;
static bool active_ready;
static int audio_rate;

static long long bounded_int(mp_obj_t obj, long long low, long long high)
{
    if (!mp_obj_is_int(obj)) {
        mp_raise_TypeError(MP_ERROR_TEXT("expected an integer"));
    }
    long long value = mp_obj_get_ll(obj);
    if (value < low || value > high) {
        mp_raise_ValueError(MP_ERROR_TEXT("integer out of range"));
    }
    return value;
}

static const char *event_string(mp_obj_t arg)
{
    if (!mp_obj_is_str(arg)) {
        mp_raise_TypeError(MP_ERROR_TEXT("event must be a string"));
    }
    size_t len;
    const char *str = mp_obj_str_get_data(arg, &len);
    if (len == 0 || len > 24 || memchr(str, 0, len) != NULL) {
        mp_raise_ValueError(MP_ERROR_TEXT("invalid event"));
    }
    return str;
}

static void require_active(void)
{
    if (!active_ready) {
        mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("reset or import Pip first"));
    }
}

static mp_obj_t mood_obj(int mood)
{
    const char *name = pip_host_mood_name(mood);
    return name ? mp_obj_new_str(name, strlen(name)) : mp_const_none;
}

static mp_obj_t pip_reset(mp_obj_t seed_arg, mp_obj_t now_arg, mp_obj_t tz_arg)
{
    uint32_t seed = bounded_int(seed_arg, 0, UINT32_MAX);
    int64_t now = bounded_int(now_arg, 0, MAX_UNIX);
    int tz = bounded_int(tz_arg, -MAX_TZ, MAX_TZ);
    if (now + (int64_t)tz * 60 < 0) {
        mp_raise_ValueError(MP_ERROR_TEXT("local Unix time predates epoch"));
    }
    pet_init(&active, now, tz, seed);
    pet_settle(&active, tz);
    tz_minutes = tz;
    active_ready = true;
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_3(pip_reset_obj, pip_reset);

static mp_obj_t pip_advance(mp_obj_t now_arg)
{
    require_active();
    int64_t now = bounded_int(now_arg, 0, MAX_UNIX);
    if (!pip_host_update(&active, now, tz_minutes)) {
        mp_raise_ValueError(MP_ERROR_TEXT("Unix time cannot go backwards"));
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(pip_advance_obj, pip_advance);

static mp_obj_t pip_event(mp_obj_t arg)
{
    require_active();
    int result = pip_host_event(&active, event_string(arg), tz_minutes);
    if (result == -2) {
        mp_raise_ValueError(MP_ERROR_TEXT("unknown or unavailable pet event"));
    }
    return mood_obj(result);
}
static MP_DEFINE_CONST_FUN_OBJ_1(pip_event_obj, pip_event);

static mp_obj_t pip_status(void)
{
    require_active();
    static const qstr reason_ids[] = {
        [PET_WHY_ASLEEP] = MP_QSTR_asleep, [PET_WHY_RARE] = MP_QSTR_rare,
        [PET_WHY_BODY] = MP_QSTR_body, [PET_WHY_AFTER] = MP_QSTR_after,
        [PET_WHY_URGE] = MP_QSTR_urge, [PET_WHY_NIGHT] = MP_QSTR_night,
        [PET_WHY_SITU] = MP_QSTR_situation, [PET_WHY_POOL] = MP_QSTR_palette,
    };
    static const qstr needs_ids[] = {
        MP_QSTR_food, MP_QSTR_energy, MP_QSTR_fun, MP_QSTR_love, MP_QSTR_walk,
    };
    int32_t fields[5];
    float values[7];
    int64_t now;
    pip_host_observe(&active, tz_minutes, fields, values, &now);
    mp_obj_t result = mp_obj_new_dict(7);
    mp_obj_t reason = mp_obj_new_dict(4);
    mp_obj_t needs = mp_obj_new_dict(5);
    for (size_t i = 0; i < sizeof needs_ids / sizeof needs_ids[0]; ++i) {
        mp_obj_dict_store(needs, MP_OBJ_NEW_QSTR(needs_ids[i]), mp_obj_new_float(values[i]));
    }
    mp_obj_dict_store(reason, MP_OBJ_NEW_QSTR(MP_QSTR_kind), MP_OBJ_NEW_QSTR(reason_ids[fields[1]]));
    mp_obj_dict_store(reason, MP_OBJ_NEW_QSTR(MP_QSTR_which), mp_obj_new_int(fields[2]));
    mp_obj_dict_store(reason, MP_OBJ_NEW_QSTR(MP_QSTR_value), mp_obj_new_float(values[6]));
    mp_obj_dict_store(reason, MP_OBJ_NEW_QSTR(MP_QSTR_hold), mp_obj_new_int(fields[3]));

    mp_obj_dict_store(result, MP_OBJ_NEW_QSTR(MP_QSTR_mood), mood_obj(fields[0]));
    mp_obj_dict_store(result, MP_OBJ_NEW_QSTR(MP_QSTR_reason), reason);
    mp_obj_dict_store(result, MP_OBJ_NEW_QSTR(MP_QSTR_needs), needs);
    mp_obj_dict_store(result, MP_OBJ_NEW_QSTR(MP_QSTR_asleep), mp_obj_new_bool(fields[4]));
    mp_obj_dict_store(result, MP_OBJ_NEW_QSTR(MP_QSTR_now), mp_obj_new_int_from_ll(now));
    mp_obj_dict_store(result, MP_OBJ_NEW_QSTR(MP_QSTR_tz_min), mp_obj_new_int(tz_minutes));
    mp_obj_dict_store(result, MP_OBJ_NEW_QSTR(MP_QSTR_valence), mp_obj_new_float(values[5]));
    return result;
}
static MP_DEFINE_CONST_FUN_OBJ_0(pip_status_obj, pip_status);

static void write_be(uint8_t *out, uint64_t value, size_t n)
{
    while (n > 0) {
        out[--n] = (uint8_t)value;
        value >>= 8;
    }
}

static uint64_t read_be(const uint8_t *p, size_t n)
{
    uint64_t value = 0;
    while (n-- > 0) {
        value = (value << 8) | *p++;
    }
    return value;
}

static uint32_t crc32_add(uint32_t crc, const uint8_t *p, size_t len)
{
    while (len-- > 0) {
        crc ^= *p++;
        for (unsigned i = 0; i < 8; ++i) {
            crc = (crc >> 1) ^ (UINT32_C(0xedb88320) & (0u - (crc & 1u)));
        }
    }
    return crc;
}

static uint32_t state_crc(const uint8_t *blob)
{
    return ~crc32_add(crc32_add(UINT32_MAX, blob, 22), blob + STATE_HEAD, sizeof active);
}

static uint64_t state_layout(void)
{
    const uint32_t endian_marker = 1;
    return pip_host_layout() ^ ((uint64_t)*(const uint8_t *)&endian_marker << 60);
}

static mp_obj_t pip_export_state(void)
{
    require_active();
    uint8_t blob[STATE_HEAD + sizeof active];
    memcpy(blob, "MGPN", 4);
    blob[4] = STATE_FMT;
    blob[5] = PET_VERSION;
    write_be(blob + 6, (uint16_t)(tz_minutes + MAX_TZ), 2);
    write_be(blob + 8, state_layout(), 8);
    write_be(blob + 16, VENDOR_TAG, 4);
    write_be(blob + 20, sizeof active, 2);
    memcpy(blob + STATE_HEAD, &active, sizeof active);
    write_be(blob + 22, state_crc(blob), 4);
    return mp_obj_new_bytes(blob, sizeof blob);
}
static MP_DEFINE_CONST_FUN_OBJ_0(pip_export_state_obj, pip_export_state);

static mp_obj_t pip_import_state(mp_obj_t obj)
{
    mp_buffer_info_t view;
    mp_get_buffer_raise(obj, &view, MP_BUFFER_READ);
    const uint8_t *p = view.buf;
    if (view.len != STATE_HEAD + sizeof active || memcmp(p, "MGPN", 4) ||
        p[4] != STATE_FMT || p[5] != PET_VERSION ||
        read_be(p + 6, 2) > 2 * MAX_TZ || read_be(p + 8, 8) != state_layout() ||
        read_be(p + 16, 4) != VENDOR_TAG || read_be(p + 20, 2) != sizeof active ||
        read_be(p + 22, 4) != state_crc(p)) {
        mp_raise_ValueError(MP_ERROR_TEXT("incompatible or corrupt Pip snapshot"));
    }
    int tz = (int)read_be(p + 6, 2) - MAX_TZ;
    if (!pip_host_restore(&active, p + STATE_HEAD, sizeof active, tz)) {
        mp_raise_ValueError(MP_ERROR_TEXT("invalid Pip state"));
    }
    tz_minutes = tz;
    active_ready = true;
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(pip_import_state_obj, pip_import_state);

static mp_obj_t pip_voice_start(size_t n_args, const mp_obj_t *args)
{
    const char *name = event_string(args[0]);
    int rate = n_args > 1 ? bounded_int(args[1], 8000, 48000) : 16000;
    int i = 0;
    for (; i < VOICE_COUNT; ++i) {
        if (!strcmp(name, voice_name(i))) {
            break;
        }
    }
    if (i == VOICE_COUNT) {
        mp_raise_ValueError(MP_ERROR_TEXT("unknown voice sound"));
    }
    if (audio_rate != rate) {
        voice_init(rate);
        audio_rate = rate;
    }
    voice_say(i);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(pip_voice_start_obj, 1, 2, pip_voice_start);

static mp_obj_t pip_voice_render_into(mp_obj_t obj)
{
    mp_buffer_info_t view;
    mp_get_buffer_raise(obj, &view, MP_BUFFER_WRITE);
    if (view.len < 2 || view.len > VOICE_MAX_BYTES || view.len % 2) {
        mp_raise_ValueError(MP_ERROR_TEXT("voice buffer must be even, 2..2048 bytes"));
    }
    uint8_t *out = view.buf;
    size_t left = view.len / 2;
    int16_t samples[VOICE_BLOCK];
    while (left > 0) {
        size_t n = left > VOICE_BLOCK ? VOICE_BLOCK : left;
        voice_render(samples, (int)n);
        for (size_t i = 0; i < n; ++i) {
            /* Explicit 16-bit little-endian PCM; no alignment assumptions
             * on the caller's bytearray or memoryview.
             */
            uint16_t value = (uint16_t)samples[i];
            *out++ = (uint8_t)value;
            *out++ = (uint8_t)(value >> 8);
        }
        left -= n;
    }
    return mp_obj_new_bool(voice_busy());
}
static MP_DEFINE_CONST_FUN_OBJ_1(pip_voice_render_into_obj, pip_voice_render_into);

static mp_obj_t pip_eyes_draw_into(size_t n_args, const mp_obj_t *args)
{
    int w = bounded_int(args[1], PIP_EYE_MIN_W, PIP_EYE_MAX_W);
    int h = bounded_int(args[2], PIP_EYE_MIN_H, PIP_EYE_MAX_H);
    mp_obj_t *items;
    mp_obj_get_array_fixed_n(args[3], PIP_EYE_POSE_SIZE, &items);
    float pose[PIP_EYE_POSE_SIZE];
    for (size_t i = 0; i < PIP_EYE_POSE_SIZE; ++i) {
        pose[i] = (float)mp_obj_get_float(items[i]);
    }
    bool swapped = n_args == 4 || mp_obj_is_true(args[4]);
    mp_buffer_info_t view;
    mp_get_buffer_raise(args[0], &view, MP_BUFFER_WRITE);
    // Never reinterpret the backing storage of wider typed arrays.
    if (view.typecode != BYTEARRAY_TYPECODE && view.typecode != 'B' && view.typecode != 'b') {
        mp_raise_TypeError(MP_ERROR_TEXT("eye tile requires a writable byte buffer"));
    }
    face_rect_t area;
    if (view.len != (size_t)w * (size_t)h * sizeof(uint16_t) ||
        !pip_eyes_tile_draw(view.buf, view.len / sizeof(uint16_t), w, h, pose, swapped, &area)) {
        mp_raise_ValueError(MP_ERROR_TEXT("invalid eye tile size, alignment or pose"));
    }
    mp_obj_t corners[] = {
        mp_obj_new_int(area.x1), mp_obj_new_int(area.y1),
        mp_obj_new_int(area.x2), mp_obj_new_int(area.y2),
    };
    return mp_obj_new_tuple(4, corners);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(pip_eyes_draw_into_obj, 4, 5, pip_eyes_draw_into);

static const mp_rom_map_elem_t pip_native_globals_table[] = {
    {MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_pip_native)},
    {MP_ROM_QSTR(MP_QSTR_ABI_VERSION), MP_ROM_INT(1)},
    {MP_ROM_QSTR(MP_QSTR_MAX_STATE_BYTES), MP_ROM_INT(STATE_HEAD + 256)},
    {MP_ROM_QSTR(MP_QSTR_VOICE_MAX_BYTES), MP_ROM_INT(VOICE_MAX_BYTES)},
    {MP_ROM_QSTR(MP_QSTR_EYES_MAX_WIDTH), MP_ROM_INT(PIP_EYE_MAX_W)},
    {MP_ROM_QSTR(MP_QSTR_EYES_MAX_HEIGHT), MP_ROM_INT(PIP_EYE_MAX_H)},
    {MP_ROM_QSTR(MP_QSTR_EYES_BLACK_KEY), MP_ROM_INT(0)},
    {MP_ROM_QSTR(MP_QSTR_reset), MP_ROM_PTR(&pip_reset_obj)},
    {MP_ROM_QSTR(MP_QSTR_advance), MP_ROM_PTR(&pip_advance_obj)},
    {MP_ROM_QSTR(MP_QSTR_event), MP_ROM_PTR(&pip_event_obj)},
    {MP_ROM_QSTR(MP_QSTR_status), MP_ROM_PTR(&pip_status_obj)},
    {MP_ROM_QSTR(MP_QSTR_export_state), MP_ROM_PTR(&pip_export_state_obj)},
    {MP_ROM_QSTR(MP_QSTR_import_state), MP_ROM_PTR(&pip_import_state_obj)},
    {MP_ROM_QSTR(MP_QSTR_voice_start), MP_ROM_PTR(&pip_voice_start_obj)},
    {MP_ROM_QSTR(MP_QSTR_voice_render_into), MP_ROM_PTR(&pip_voice_render_into_obj)},
    {MP_ROM_QSTR(MP_QSTR_eyes_draw_into), MP_ROM_PTR(&pip_eyes_draw_into_obj)},
};
static MP_DEFINE_CONST_DICT(pip_native_globals, pip_native_globals_table);

const mp_obj_module_t pip_native_module = {
    .base = {&mp_type_module},
    .globals = (mp_obj_dict_t *)&pip_native_globals,
};

MP_REGISTER_MODULE(MP_QSTR_pip_native, pip_native_module);
