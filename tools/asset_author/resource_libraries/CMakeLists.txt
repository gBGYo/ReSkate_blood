cmake_minimum_required(VERSION 3.24)
project(BloodResourceLibraries LANGUAGES C CXX)
if(NOT WIN32 OR NOT MSVC OR NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
    message(FATAL_ERROR "Resource libraries require Windows, MSVC and x64.")
endif()
set(RESKATE_SOURCE_DIR "" CACHE PATH "External ReSkate source tree (read-only)")
if(NOT EXISTS "${RESKATE_SOURCE_DIR}/Engine/Vfs/game_bundles.h")
    message(FATAL_ERROR "Set RESKATE_SOURCE_DIR to a ReSkate checkout with general resource APIs.")
endif()
set(CMAKE_MSVC_RUNTIME_LIBRARY MultiThreaded)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# This is a dependency build definition, not a vendored SDK. All source files
# stay in the external checkout; only the libraries required by the author build.
function(resource_library name)
    set(sources ${ARGN})
    list(TRANSFORM sources PREPEND "${RESKATE_SOURCE_DIR}/")
    add_library(dingosdk_${name} STATIC ${sources})
    target_include_directories(dingosdk_${name} PUBLIC "${RESKATE_SOURCE_DIR}")
    target_compile_definitions(dingosdk_${name} PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX UNICODE _UNICODE)
    target_compile_options(dingosdk_${name} PRIVATE /W4 /WX /permissive- /EHsc)
endfunction()

add_library(dingosdk_miniz STATIC "${RESKATE_SOURCE_DIR}/External/miniz/miniz.c")
target_include_directories(dingosdk_miniz SYSTEM PUBLIC "${RESKATE_SOURCE_DIR}/External/miniz")
target_compile_definitions(dingosdk_miniz PUBLIC MINIZ_NO_ARCHIVE_WRITING_APIS MINIZ_NO_ZLIB_APIS MINIZ_NO_STDIO MINIZ_NO_TIME)
add_library(dingosdk_lz4 STATIC "${RESKATE_SOURCE_DIR}/External/lz4/lz4.c")
target_include_directories(dingosdk_lz4 SYSTEM PUBLIC "${RESKATE_SOURCE_DIR}/External/lz4")
file(GLOB zstd_sources CONFIGURE_DEPENDS "${RESKATE_SOURCE_DIR}/External/zstd/lib/common/*.c"
    "${RESKATE_SOURCE_DIR}/External/zstd/lib/compress/*.c" "${RESKATE_SOURCE_DIR}/External/zstd/lib/decompress/*.c")
add_library(dingosdk_zstd STATIC ${zstd_sources})
target_include_directories(dingosdk_zstd SYSTEM PUBLIC "${RESKATE_SOURCE_DIR}/External/zstd/lib")
target_compile_definitions(dingosdk_zstd PRIVATE ZSTD_LEGACY_SUPPORT=0 ZSTD_DISABLE_ASM)

resource_library(json Engine/Core/Json/json.cpp)
target_include_directories(dingosdk_json SYSTEM PRIVATE "${RESKATE_SOURCE_DIR}/External")
resource_library(frostbite
    Engine/Resource/binary_io.cpp Engine/Resource/binary_bundle.cpp Engine/Resource/cas_codec.cpp
    Engine/Resource/ebx_document.cpp Engine/Resource/ebx_fixup_repair.cpp Engine/Resource/ebx_merge.cpp
    Engine/Resource/material_grid.cpp Engine/Resource/shader_lookup.cpp Engine/Resource/bundle_ref_table.cpp
    Engine/Resource/ebx_writer.cpp Engine/Resource/toc.cpp Engine/Resource/texture.cpp
    Engine/Resource/mesh_set.cpp Engine/Resource/skeleton_asset.cpp)
target_include_directories(dingosdk_frostbite SYSTEM PRIVATE "${RESKATE_SOURCE_DIR}/External/bcdec")
target_link_libraries(dingosdk_frostbite PRIVATE dingosdk_lz4 dingosdk_zstd dingosdk_miniz)
resource_library(native_db Engine/Vfs/native_db.cpp)
resource_library(game_archives Engine/Vfs/game_archives.cpp Engine/Vfs/game_bundles.cpp
    Engine/Vfs/item_thumbnails.cpp Engine/Vfs/game_textures.cpp)
target_link_libraries(dingosdk_game_archives PUBLIC dingosdk_native_db dingosdk_frostbite)
resource_library(mod_list Engine/Vfs/mod_list.cpp)
target_link_libraries(dingosdk_mod_list PUBLIC dingosdk_json)
resource_library(content_cache Engine/Vfs/content_cache.cpp Engine/Vfs/content_catalogs.cpp)
target_link_libraries(dingosdk_content_cache PUBLIC dingosdk_json)
resource_library(mods
    Engine/Vfs/mod_catalog.cpp Engine/Vfs/mod_merge.cpp Engine/Vfs/mod_merge_files.cpp
    Engine/Vfs/mod_merge_stamp.cpp Engine/Vfs/mod_merge_cas_store.cpp Engine/Vfs/mod_merge_combine.cpp
    Engine/Vfs/mod_merge_overrides.cpp Engine/Vfs/mod_merge_conflicts.cpp Engine/Vfs/mod_merge_scan_cache.cpp
    Engine/Vfs/mod_merge_textures.cpp Engine/Vfs/mod_merge_grid.cpp Engine/Vfs/mod_merge_load_screens.cpp
    Engine/Vfs/mod_music.cpp Engine/Vfs/mod_scoring.cpp Engine/Vfs/mod_store_copies.cpp
    Engine/Vfs/mod_item_sources.cpp Engine/Vfs/builtin_packs.cpp)
target_link_libraries(dingosdk_mods PUBLIC dingosdk_json dingosdk_mod_list PRIVATE
    dingosdk_game_archives dingosdk_native_db dingosdk_frostbite dingosdk_content_cache
    dingosdk_miniz dingosdk_zstd shell32 bcrypt)
