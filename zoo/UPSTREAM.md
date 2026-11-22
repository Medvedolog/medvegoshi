# Zoo: происхождение заимствованных тестов и исходников

В `zoo/upstream/` хранятся **неизменённые** исходные тесты других проектов.
Они служат техническими образцами для разработки собственных тестов
MicroPython и сами по себе **не включаются в прошивку**.

## Pip-KeyPet — David Novikov

- Источник: https://github.com/NovikovVisuals/Pip-KeyPet
- Коммит: `b505d9393bd9b8c0b076c0ef7a4d46921db69071` (14.11.2026)
- Лицензия: MIT, `upstream/pip/LICENSE`
- Без изменений скопированы:
  - `sim/face_test.c` → `upstream/pip/sim/face_test.c`: тесты рисования глаз.
  - `sim/maze_test.c` → `upstream/pip/sim/maze_test.c`: тесты мини-игры «лабиринт».
  - `sim/pet_test.c` → `upstream/pip/sim/pet_test.c`: тесты потребностей/поведения питомца.
  - `ui/face.h` → `upstream/pip/ui/face.h`: описание оригинального C API графики глаз.
  - `ui/face.c`, `ui/maze.c`, `ui/maze.h`, `ui/pet.c`, `ui/pet.h`, `ui/moods.h`
    → `upstream/pip/ui/`: исходный MIT-движок для компиляции исходных тестов.

Команда `sh zoo/upstream/pip/run_tests.sh` собирает три оригинальных C-теста
на компьютере (нужен `cc` и `libm`). Эти тесты также включены в GitHub Actions.
Они проверяют оригинальный Pip-KeyPet, не наш рендерер `zoo/pip/face.py`.

Наш `zoo/pip/face.py` **написан заново**, а не является переводом
`ui/face.c`. Он использует как вдохновение идею эмоциональных глаз.

## Giraffegotchi — Elliot Boney

- Источник: https://github.com/elliotboney/giraffegotchi
- Коммит: `440a9545f5447c32cf48b8cb93f6258fbd842d13` (04.07.2026)
- Лицензия: MIT, `upstream/giraffegotchi/LICENSE`
- Без изменений скопированы:
  - `test/test_pet/test_pet.cpp` → `upstream/giraffegotchi/test_pet.cpp`;
  - `test/test_sky/test_sky.cpp` → `upstream/giraffegotchi/test_sky.cpp`.

Эти тесты показывают проверки развития состояний питомца, ночного
режима, расчёта дня и солнца. Чужие PNG/спрайты в Zoo не копировались.

## ESP32-TamaPetchi — CyberXcyborg

- Источник: https://github.com/CyberXcyborg/ESP32-TamaPetchi
- Коммит: `ade0db1111811ef7cbc343149368a7d781aa4e31` (25.06.2026)
- Лицензия: MIT, `upstream/tamapetchi/LICENSE`
- Без изменений скопированы:
  - `test/test_day_night.cpp` → `upstream/tamapetchi/test_day_night.cpp`;
  - `test/test_backup.cpp` → `upstream/tamapetchi/test_backup.cpp`.

Эти тесты полезны для будущей проверки смены суток и
надёжности сохранений `capi.json` / `brain.bin`.

## Общее правило

1. Для цитирования тестов используйте ссылки на конкретный коммит.
2. Не переименовывайте чужие тесты с претензией на авторство MedveGoshi.
3. При переносе функций выполняйте отдельную адаптацию под MicroPython,
   пишите **наши исполняемые тесты** в `zoo/tests/` и фиксируйте источник.
4. Никаких прямых зависимостей MicroPython-прошивки от `zoo/upstream`.
5. Не включайте чужие картинки/звуки автоматически только потому,
   что исходный код репозитория имеет MIT-лицензию.

Для будущих поступлений фиксируйте: **source URL · SHA · автор · лицензия ·
список файлов · модификации · наличие бинарных материалов**.
