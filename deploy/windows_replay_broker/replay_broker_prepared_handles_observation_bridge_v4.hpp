#pragma once

#include "replay_broker_contract_v4.hpp"

#include <Windows.h>

#include <array>
#include <cstdint>
#include <optional>
#include <string>

namespace vast::replay_broker::v4 {

class PreparedOsHandleSet;

namespace detail {

struct FrozenArtifactObservationMetadata final {
  ArtifactRole role;
  std::string file_sha256;
  std::uint64_t size_bytes;
};

struct ArtifactObservationSeed final {
  // `handles` is a non-owning borrow: never call CloseHandle on these values.
  // The caller must keep the current PreparedOsHandleSet PIMPL owner alive and
  // must not move or move-assign that owner while this seed is used. The borrow
  // ends when that current owner destroys or move-assigns its PIMPL.
  std::array<HANDLE, 6> handles{};
  std::array<FrozenArtifactObservationMetadata, 6> artifacts{};
};

class PreparedHandleObservationBridge final {
 public:
  [[nodiscard]] static std::optional<ArtifactObservationSeed> snapshot(
      const PreparedOsHandleSet& prepared) noexcept;
};

}  // namespace detail
}  // namespace vast::replay_broker::v4
