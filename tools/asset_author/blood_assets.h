// Blood asset recipes ported from ReSkate feature/blood, ece0fb0873de771dd52accb8d0ab8cc7956f939b.
#pragma once
#include <array>
#include <cmath>
#include <cstdint>
#include <string>
#include <string_view>

namespace blood::assets {
enum class BloodColor : unsigned { red, green, blue, pink };
inline constexpr std::array blood_color_names={"Red","Green","Blue","Pink"};
inline constexpr std::array blood_color_suffixes={"","_green","_blue","_pink"};
inline constexpr bool valid_blood_color(BloodColor color) noexcept {return unsigned(color)<blood_color_names.size();}
inline std::string blood_colored_asset(std::string_view name,BloodColor color) {
    std::string result(name);
    if (valid_blood_color(color)) result.insert(result.ends_with("_dv") ? result.size()-3 : result.size(),blood_color_suffixes[unsigned(color)]);
    return result;
}
// Preserve the original red pigment exactly; other presets reuse its shading.
inline std::array<std::uint8_t,3> blood_pixel(BloodColor color,std::uint8_t red,std::uint8_t green,std::uint8_t blue) noexcept {
    switch (color) {
    case BloodColor::green: return {green,red,blue};
    case BloodColor::blue: return {green,blue,red};
    case BloodColor::pink: return {red,std::uint8_t(red/4),std::uint8_t(red*3/4)};
    default: return {red,green,blue};
    }
}
inline constexpr float blood_max_emission_scale = 2;
inline constexpr std::array blood_asset_names = {
    "effects/reskate/gbgyo_blood/ebp_blood_spray", "effects/reskate/gbgyo_blood/ebp_blood_droplets", "effects/reskate/gbgyo_blood/ebp_blood_trail",
    "effects/reskate/gbgyo_blood/ebp_blood_spray_light", "effects/reskate/gbgyo_blood/ebp_blood_droplets_light", "effects/reskate/gbgyo_blood/ebp_blood_trail_light",
    "effects/reskate/gbgyo_blood/ebp_blood_spray_heavy", "effects/reskate/gbgyo_blood/ebp_blood_droplets_heavy", "effects/reskate/gbgyo_blood/ebp_blood_trail_heavy"};
inline constexpr std::array blood_ground_shapes = {
    "splash_01", "splash_02", "splash_03", "splash_04", "splash_05",
    "smear_01", "smear_02", "smear_03", "smear_04", "smear_05",
    "pool_01", "pool_02", "pool_03", "pool_04", "pool_05",
    "drops_01", "drops_02", "drops_03", "drops_04", "drops_05"};
inline std::string blood_ground_stem(unsigned shape, unsigned color) {
    return std::string("world/materials/decal/reskate_blood/reskate_blood_")+
        blood_ground_shapes.at(shape)+blood_color_suffixes.at(color);
}
}
