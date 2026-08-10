#pragma once

#include <cmath>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <string>

namespace vast_policy_trace {

inline std::string json_escape(const std::string& value) {
  std::ostringstream out;
  for (const unsigned char ch : value) {
    switch (ch) {
      case '"': out << "\\\""; break;
      case '\\': out << "\\\\"; break;
      case '\b': out << "\\b"; break;
      case '\f': out << "\\f"; break;
      case '\n': out << "\\n"; break;
      case '\r': out << "\\r"; break;
      case '\t': out << "\\t"; break;
      default:
        if (ch < 0x20) {
          out << "\\u" << std::hex << std::setw(4) << std::setfill('0')
              << static_cast<int>(ch) << std::dec << std::setfill(' ');
        } else {
          out << static_cast<char>(ch);
        }
    }
  }
  return out.str();
}

inline std::string json_quote(const std::string& value) {
  return "\"" + json_escape(value) + "\"";
}

inline std::string json_number(double value) {
  if (!std::isfinite(value)) {
    throw std::runtime_error("Policy trace cannot serialize a non-finite number");
  }
  std::ostringstream out;
  out << std::setprecision(17) << value;
  return out.str();
}

inline std::string csv_escape(const std::string& value) {
  if (value.find_first_of(",\"\r\n") == std::string::npos) {
    return value;
  }
  std::string escaped;
  escaped.reserve(value.size() + 2);
  escaped.push_back('"');
  for (const char ch : value) {
    if (ch == '"') {
      escaped.push_back('"');
    }
    escaped.push_back(ch);
  }
  escaped.push_back('"');
  return escaped;
}

}  // namespace vast_policy_trace
