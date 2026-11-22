# Благодарности, авторство и лицензии

## Оригинальный проект

**MedveGoshi основан на [Capigoshi](https://github.com/rjcaubit/capigoshi)**, автор репозитория — **rjcaubit**. Особая благодарность **Жуану (João)**: в возрасте 9 лет он придумал первоначальных персонажей, их движения и поведение. MedveGoshi — самостоятельная локализация и дальнейшая разработка, не официальный релиз авторов Capigoshi.

Исходный программный код распространяется по [лицензии MIT](LICENSE); копию лицензии и юридическое уведомление об авторских правах необходимо сохранять при распространении производных версий. **Лицензия программного кода не распространяется автоматически на все рисунки, звуковые записи и внешние материалы.**

## Иллюстрации и персонажи

Оригинальные рисунки Жуана находятся среди материалов `docs/img/joao_*` и `docs/img/joao-desenhos.jpg`, опубликованных с разрешения семьи. **Авторские права на рисунки принадлежат Жуану и его семье**; они не охватываются лицензией MIT на программный код. Для использования самих рисунков за пределами проекта требуется отдельное разрешение — обратитесь к [автору оригинального проекта](https://github.com/rjcaubit/capigoshi/issues). Исходный код, программно рисующий персонажей, лицензируется отдельно.

## Звуки, включённые в репозиторий

| Материалы | Источник | Условия |
|---|---|---|
| `sons/*.raw` | [Kenney, Interface Sounds](https://kenney.nl/assets/interface-sounds) | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) |
| `sons/LICENCA-kenney.txt` | Сведения о звуковом пакете | Сохранять вместе с материалами |

## Звуки, не включённые в репозиторий

Дополнительные эффекты и голосовые записи по ссылкам из [`sons/pixabay.sh`](sons/pixabay.sh) распространяются по [Pixabay Content License](https://pixabay.com/service/license-summary/). Использование в составе проекта возможно в пределах лицензии, **повторное распространение отдельных исходных файлов не допускается**. Поэтому пользователь загружает их самостоятельно, а результат хранится в исключённой из Git папке `sons/extra/`.

Авторы выбранных эффектов, указанные в оригинальном проекте: freesound_community, DRAGON-STUDIO, Universfield, Yodguard, Vadim_Makes_Sound, ShidenBeatsMusic, Phoenix_Connection_Brazil, RibhavAgrawal.

## Программные компоненты и технические материалы

- [MicroPython](https://micropython.org/) — MIT.
- Аппаратные регистры AXP2101 изучены по примерам [Waveshare](https://github.com/waveshareteam/ESP32-S3-Touch-LCD-1.83) и [XPowersLib](https://github.com/lewisxhe/XPowersLib), согласно авторской документации Capigoshi.
- В оригинальных HTML-страницах используются шрифты [Fredoka](https://fonts.google.com/specimen/Fredoka), [Nunito](https://fonts.google.com/specimen/Nunito), [Press Start 2P](https://fonts.google.com/specimen/Press+Start+2P); соблюдайте условия их лицензий.
- Для планируемого порта AMOLED V1 рассматривается [dobodu/Lilygo_Waveshare_Amoled_Micropython](https://github.com/dobodu/Lilygo_Waveshare_Amoled_Micropython). **Код стороннего драйвера пока не перенесён в MedveGoshi**; перед копированием проверьте его актуальную лицензию и необходимость дополнительных уведомлений.

Спасибо разработчикам и сообществу Capigoshi за открытый код и документацию.
