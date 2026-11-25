/* The plugin ABI only ever grows at the end: every member keeps its offset, so plugins built
 * against an older header keep working. A failed assertion here means a member moved. */
#include <stddef.h>

#include "mh4u_plugin.h"

#define P sizeof(void *)
#define PROGRAM_ID ((8 + 2 * P + 7) / 8 * 8)
#define FN(i) (PROGRAM_ID + 8 + (i) * P)

_Static_assert(MH4U_PLUGIN_ABI == 3, "a new ABI: add its members' offsets below");
_Static_assert(offsetof(MH4UPluginHost, abi) == 0, "abi moved");
_Static_assert(offsetof(MH4UPluginHost, size) == 4, "size moved");
_Static_assert(offsetof(MH4UPluginHost, mod_name) == 8, "mod_name moved");
_Static_assert(offsetof(MH4UPluginHost, mod_dir) == 8 + P, "mod_dir moved");
_Static_assert(offsetof(MH4UPluginHost, program_id) == PROGRAM_ID, "program_id moved");
_Static_assert(offsetof(MH4UPluginHost, hook) == FN(0), "hook moved");
_Static_assert(offsetof(MH4UPluginHost, call_original) == FN(1), "call_original moved");
_Static_assert(offsetof(MH4UPluginHost, skip_original) == FN(2), "skip_original moved");
_Static_assert(offsetof(MH4UPluginHost, reg) == FN(3), "reg moved");
_Static_assert(offsetof(MH4UPluginHost, set_reg) == FN(4), "set_reg moved");
_Static_assert(offsetof(MH4UPluginHost, read32) == FN(5), "read32 moved");
_Static_assert(offsetof(MH4UPluginHost, read16) == FN(6), "read16 moved");
_Static_assert(offsetof(MH4UPluginHost, read8) == FN(7), "read8 moved");
_Static_assert(offsetof(MH4UPluginHost, write32) == FN(8), "write32 moved");
_Static_assert(offsetof(MH4UPluginHost, write16) == FN(9), "write16 moved");
_Static_assert(offsetof(MH4UPluginHost, write8) == FN(10), "write8 moved");
_Static_assert(offsetof(MH4UPluginHost, guest_pointer) == FN(11), "guest_pointer moved");
_Static_assert(offsetof(MH4UPluginHost, log) == FN(12), "log moved");
_Static_assert(offsetof(MH4UPluginHost, config) == FN(13), "config moved");
_Static_assert(offsetof(MH4UPluginHost, on_frame) == FN(14), "on_frame moved");
_Static_assert(offsetof(MH4UPluginHost, alloc) == FN(15), "alloc moved (ABI 2)");
_Static_assert(offsetof(MH4UPluginHost, free) == FN(16), "free moved (ABI 2)");
_Static_assert(offsetof(MH4UPluginHost, call) == FN(17), "call moved (ABI 3)");
_Static_assert(sizeof(MH4UPluginHost) == FN(18), "a member was added: raise MH4U_PLUGIN_ABI");

int main(void) {
    return 0;
}
