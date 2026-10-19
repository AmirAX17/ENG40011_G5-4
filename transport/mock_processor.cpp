#include "processor.h"

#include <algorithm>
#include <cctype>

static std::string lowercase(std::string text) {
    std::transform(
        text.begin(),
        text.end(),
        text.begin(),
        [](unsigned char c) {
            return static_cast<char>(std::tolower(c));
        }
    );

    return text;
}

std::string process_chunk(
    const std::string& session_context,
    const std::string& new_chunk
) {
    std::string old_text = lowercase(session_context);
    std::string new_text = lowercase(new_chunk);

    // Temporary test logic only.
    // This file will later be replaced by the real AI processor.
    if (
        old_text.find("no known allergies") != std::string::npos &&
        new_text.find("allergic to penicillin") != std::string::npos
    ) {
        return "WARNING: Contradiction detected. Earlier information stated "
               "no known allergies, but the latest transcript reports a "
               "penicillin allergy.";
    }

    return "";
}
