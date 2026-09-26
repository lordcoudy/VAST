#include "checkpoint_analytics_execution_client.hpp"

#include <iostream>
#include <string>

int main() {
  const char* accepted[] = {
      "Intel(R) Core(TM) i7-14700K",
      "GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266",
      "CPU",
  };
  for (const char* value : accepted) {
    if (!vast::checkpoint_analytics_stable_device_id(value)) {
      std::cerr << "device id was rejected: " << value << '\n';
      return 1;
    }
  }
  const std::string rejected[] = {
      "",
      " Intel(R) Core(TM) i7-14700K",
      "Intel(R) Core(TM) i7-14700K ",
      std::string("Intel\nCore"),
      std::string(257, 'x'),
  };
  for (const std::string& value : rejected) {
    if (vast::checkpoint_analytics_stable_device_id(value)) {
      std::cerr << "unstable device id was accepted\n";
      return 1;
    }
  }
  return 0;
}
