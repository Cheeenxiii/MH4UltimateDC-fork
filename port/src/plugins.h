// Native plugins of the enabled mods (include/mh4u_plugin.h, docs/PLUGINS.md),
// loaded with the game's code library. The rules live in plugin_host.h, which needs no Azahar.
#pragma once

#include <string>
#include <vector>

struct RCodeInfo;

namespace Port::Plugins {

/// A new code library: returns the RCodeInfo to hand to Hooks::Install, whose set_hook lets
/// plugin hooks and the port's own hooks share a hook point. Unloads the last library's plugins.
RCodeInfo Begin(const RCodeInfo& info);

/// Loads the plugins that build_game.py listed for the library at `library_path` (its
/// <program id>.plugins.tsv, next to it), in mod order. Returns lines for the log.
std::vector<std::string> Load(const std::string& library_path);

/// The plugin list's path for a code library's path.
std::string ListPath(const std::string& library_path);

} // namespace Port::Plugins
