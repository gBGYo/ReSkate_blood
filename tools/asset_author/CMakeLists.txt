cmake_minimum_required(VERSION 3.24)
project(BloodAssetAuthor LANGUAGES CXX)

if(NOT WIN32 OR NOT MSVC OR NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
    message(FATAL_ERROR "The Blood asset author requires Windows, MSVC and the x64 platform.")
endif()

set(RESKATE_SOURCE_DIR "" CACHE PATH "External ReSkate source providing general resource headers")
set(RESKATE_LIBRARY_DIR "" CACHE PATH "Directory containing the external Release resource libraries")
foreach(header IN ITEMS Engine/Vfs/game_bundles.h Engine/Resource/ebx_writer.h
        Engine/Resource/texture.h Engine/Vfs/mod_catalog.h Engine/Core/Json/json.h)
    if(NOT EXISTS "${RESKATE_SOURCE_DIR}/${header}")
        message(FATAL_ERROR "Missing general resource header: ${RESKATE_SOURCE_DIR}/${header}")
    endif()
endforeach()

# Link general asset IO and mod-merging libraries only. No runtime, plugin host,
# feature/Blood sources or prebuilt Blood executable are used from ReSkate.
set(resource_libraries game_archives native_db frostbite json mods mod_list content_cache lz4 miniz zstd)
foreach(library IN LISTS resource_libraries)
    set(location "${RESKATE_LIBRARY_DIR}/dingosdk_${library}.lib")
    if(NOT EXISTS "${location}")
        message(FATAL_ERROR "Missing ${location}. Build ReSkate's dingosdk_mods target first.")
    endif()
    add_library(reskate::${library} STATIC IMPORTED)
    set_target_properties(reskate::${library} PROPERTIES IMPORTED_LOCATION "${location}")
endforeach()

add_executable(blood_asset_author blood_asset_author.cpp blood_assets.h blood_ground_asset.h)
target_compile_features(blood_asset_author PRIVATE cxx_std_20)
target_include_directories(blood_asset_author SYSTEM PRIVATE "${RESKATE_SOURCE_DIR}")
target_compile_definitions(blood_asset_author PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX UNICODE _UNICODE)
target_compile_options(blood_asset_author PRIVATE /W4 /WX /permissive- /EHsc)
target_link_libraries(blood_asset_author PRIVATE reskate::game_archives reskate::json reskate::mods
    reskate::native_db reskate::frostbite reskate::mod_list reskate::content_cache
    reskate::lz4 reskate::miniz reskate::zstd shell32 bcrypt)
set_target_properties(blood_asset_author PROPERTIES
    MSVC_RUNTIME_LIBRARY MultiThreaded
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
    RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_BINARY_DIR}/bin")
