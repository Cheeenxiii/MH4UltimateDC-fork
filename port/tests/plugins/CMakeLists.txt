# Tests of the native plugin host (port/src/plugin_host.h) and its ABI (include/mh4u_plugin.h).
# They need no Azahar: plugin_host.h is built on its own, with dlopen as the loader.
#   cmake -S port/tests/plugins -B build/plugin-tests && cmake --build build/plugin-tests
#   ctest --test-dir build/plugin-tests --output-on-failure
cmake_minimum_required(VERSION 3.16)
project(mh4u_plugin_tests C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(REPO ${CMAKE_CURRENT_LIST_DIR}/../../..)

# The ABI's layout is checked at compile time: a member moved or removed fails this build.
add_executable(abi_layout abi_layout.c)
target_include_directories(abi_layout PRIVATE ${REPO}/include)

# Three copies of one test plugin, so each has its own state when loaded together.
foreach(n 1 2 3)
    add_library(test_plugin_${n} MODULE test_plugin.c)
    target_include_directories(test_plugin_${n} PRIVATE ${REPO}/include)
    set_target_properties(test_plugin_${n} PROPERTIES PREFIX "" C_VISIBILITY_PRESET hidden)
endforeach()

add_executable(plugin_host_test plugin_host_test.cpp)
target_include_directories(plugin_host_test PRIVATE ${REPO}/port/src ${REPO}/tools/recomp/runtime)
target_link_libraries(plugin_host_test PRIVATE ${CMAKE_DL_LIBS})
target_compile_definitions(plugin_host_test PRIVATE
    PLUGIN_1="$<TARGET_FILE:test_plugin_1>"
    PLUGIN_2="$<TARGET_FILE:test_plugin_2>"
    PLUGIN_3="$<TARGET_FILE:test_plugin_3>")
add_dependencies(plugin_host_test test_plugin_1 test_plugin_2 test_plugin_3)

enable_testing()
add_test(NAME abi_layout COMMAND abi_layout)
foreach(t chain_runs_last_mod_first_then_port_then_game
          skip_original_returns_to_the_caller
          failed_init_takes_its_hooks_back
          reset_gives_the_port_its_hooks_back
          hooking_a_missing_hook_point_fails_and_says_so
          alloc_and_free_go_through_the_games_allocator
          call_runs_a_game_function_and_restores_the_registers
          call2_passes_r3_and_floats_and_restores_the_registers)
    add_test(NAME ${t} COMMAND plugin_host_test ${t})
endforeach()
