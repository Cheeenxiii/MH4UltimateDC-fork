#include "plugins.h"

#include <fstream>
#include <memory>
#include <sstream>

#include "common/dynamic_library.h"
#include "common/logging/log.h"

// Plugins read and write guest memory through Azahar's page table, like recompiled code.
// Included last: recomp.h defines short macros (R, C_EQ, ...).
#define RC_PAGED
#include "plugin_host.h"

namespace Port::Plugins {

namespace {

void* Open(const char* path, std::string& error) {
    auto library = std::make_unique<Common::DynamicLibrary>();
    if (!library->Load(path)) {
        error = library->GetLoadError();
        return nullptr;
    }
    return library.release();
}

void* Symbol(void* library, const char* name) {
    return static_cast<Common::DynamicLibrary*>(library)->GetSymbol<void*>(name);
}

void Close(void* library) {
    delete static_cast<Common::DynamicLibrary*>(library);
}

void Sink(int level, const std::string& line) {
    switch (level) {
    case MH4U_LOG_DEBUG:
        LOG_DEBUG(Core_ARM11, "plugin {}", line);
        break;
    case MH4U_LOG_WARNING:
        LOG_WARNING(Core_ARM11, "plugin {}", line);
        break;
    case MH4U_LOG_ERROR:
        LOG_ERROR(Core_ARM11, "plugin {}", line);
        break;
    default:
        LOG_INFO(Core_ARM11, "plugin {}", line);
    }
}

} // namespace

std::string ListPath(const std::string& library_path) {
    const auto slash = library_path.find_last_of("/\\");
    const auto dot = library_path.find_last_of('.');
    const bool has_ext = dot != std::string::npos && (slash == std::string::npos || dot > slash);
    return (has_ext ? library_path.substr(0, dot) : library_path) + ".plugins.tsv";
}

RCodeInfo Begin(const RCodeInfo& info) {
    PluginHost& host = PluginHost::Get();
    host.SetLog(&Sink);
    return host.Begin(info, Loader{&Open, &Symbol, &Close});
}

std::vector<std::string> Load(const std::string& library_path) {
    std::ifstream file(ListPath(library_path), std::ios::binary);
    if (!file) {
        return {}; // no mod with a plugin when the library was built
    }
    std::stringstream text;
    text << file.rdbuf();
    return PluginHost::Get().Load(ParsePluginList(text.str()));
}

} // namespace Port::Plugins
