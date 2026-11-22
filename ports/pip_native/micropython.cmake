# Optional experimental native module; include from USER_C_MODULES.
set(PIP_NATIVE_ROOT "${CMAKE_CURRENT_LIST_DIR}/../..")
set(PIP_VENDOR_UI "${PIP_NATIVE_ROOT}/zoo/upstream/pip/ui")
add_library(usermod_pip_native INTERFACE)
target_sources(usermod_pip_native INTERFACE
    "${CMAKE_CURRENT_LIST_DIR}/mod_pip_native.c"
    "${CMAKE_CURRENT_LIST_DIR}/eyes_tile.c"
    "${PIP_NATIVE_ROOT}/zoo/pip/pet_host_bridge.c"
    "${PIP_VENDOR_UI}/face.c"
    "${PIP_VENDOR_UI}/pet.c"
    "${PIP_VENDOR_UI}/voice.c"
)
target_include_directories(usermod_pip_native INTERFACE "${PIP_VENDOR_UI}")
target_link_libraries(usermod INTERFACE usermod_pip_native)
