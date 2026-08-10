#pragma once

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>

namespace vast_weighted_proxy {

enum class Resource { Cpu, Gpu };

struct DecisionInput {
  double cpu_profile_proxy_ms = 0.0;
  double gpu_profile_proxy_ms = 0.0;
  double object_multiplier = 1.0;
  std::size_t cpu_queue_depth = 0;
  std::size_t gpu_queue_depth = 0;
  int active_cpu = 0;
  int active_gpu = 0;
  double cpu_weight = 1.0;
  double gpu_weight = 1.0;
  double gpu_heavy_multiplier = 1.0;
  double score_epsilon = 1e-9;
  Resource stage_preference = Resource::Cpu;
};

struct Decision {
  Resource selected = Resource::Cpu;
  double cpu_score_ms = 0.0;
  double gpu_score_ms = 0.0;
  std::string reason;
};

inline Decision choose(const DecisionInput& input) {
  const double values[] = {
      input.cpu_profile_proxy_ms,
      input.gpu_profile_proxy_ms,
      input.object_multiplier,
      input.cpu_weight,
      input.gpu_weight,
      input.gpu_heavy_multiplier,
      input.score_epsilon,
  };
  for (const double value : values) {
    if (!std::isfinite(value)) {
      throw std::runtime_error("Weighted proxy decision contains a non-finite value");
    }
  }
  if (input.cpu_profile_proxy_ms <= 0.0 || input.gpu_profile_proxy_ms <= 0.0 ||
      input.object_multiplier <= 0.0 || input.cpu_weight <= 0.0 || input.gpu_weight <= 0.0 ||
      input.gpu_heavy_multiplier <= 0.0 || input.score_epsilon < 0.0 || input.active_cpu < 0 ||
      input.active_gpu < 0) {
    throw std::runtime_error("Weighted proxy decision contains an invalid cost parameter");
  }

  const double cpu_backlog = static_cast<double>(input.cpu_queue_depth) + input.active_cpu;
  const double gpu_backlog = static_cast<double>(input.gpu_queue_depth) + input.active_gpu;
  Decision decision;
  decision.cpu_score_ms = (cpu_backlog + 1.0) * input.cpu_profile_proxy_ms *
                          input.object_multiplier * input.cpu_weight;
  decision.gpu_score_ms = (gpu_backlog + 1.0) * input.gpu_profile_proxy_ms *
                          input.object_multiplier * input.gpu_weight * input.gpu_heavy_multiplier;

  if (decision.cpu_score_ms + input.score_epsilon < decision.gpu_score_ms) {
    decision.selected = Resource::Cpu;
    decision.reason = "minimum_weighted_proxy_score";
  } else if (decision.gpu_score_ms + input.score_epsilon < decision.cpu_score_ms) {
    decision.selected = Resource::Gpu;
    decision.reason = "minimum_weighted_proxy_score";
  } else if (input.cpu_queue_depth < input.gpu_queue_depth) {
    decision.selected = Resource::Cpu;
    decision.reason = "score_tie_lower_queue_depth";
  } else if (input.gpu_queue_depth < input.cpu_queue_depth) {
    decision.selected = Resource::Gpu;
    decision.reason = "score_tie_lower_queue_depth";
  } else {
    decision.selected = input.stage_preference;
    decision.reason = "score_tie_stage_preference";
  }
  return decision;
}

enum class UpdateSignal { None, PenalizeGpu, RewardGpu };

struct WeightPair {
  double cpu = 1.0;
  double gpu = 1.0;
};

inline bool mean_one(const WeightPair& weights, double tolerance = 1e-9) {
  return std::isfinite(weights.cpu) && std::isfinite(weights.gpu) &&
         std::abs(weights.cpu + weights.gpu - 2.0) <= tolerance;
}

inline WeightPair project_box_mean_one(const WeightPair& raw,
                                       const WeightPair& minimum,
                                       const WeightPair& maximum) {
  const double values[] = {
      raw.cpu, raw.gpu, minimum.cpu, minimum.gpu, maximum.cpu, maximum.gpu,
  };
  for (const double value : values) {
    if (!std::isfinite(value)) {
      throw std::runtime_error("Weighted proxy projection contains a non-finite value");
    }
  }
  if (minimum.cpu <= 0.0 || minimum.gpu <= 0.0 ||
      maximum.cpu < minimum.cpu || maximum.gpu < minimum.gpu ||
      minimum.cpu + minimum.gpu > 2.0 || maximum.cpu + maximum.gpu < 2.0) {
    throw std::runtime_error("Weighted proxy bounds do not intersect the mean-one plane");
  }

  double lo = std::min(raw.cpu - maximum.cpu, raw.gpu - maximum.gpu);
  double hi = std::max(raw.cpu - minimum.cpu, raw.gpu - minimum.gpu);
  for (int iteration = 0; iteration < 200; ++iteration) {
    const double shift = (lo + hi) / 2.0;
    const double cpu = std::max(minimum.cpu, std::min(maximum.cpu, raw.cpu - shift));
    const double gpu = std::max(minimum.gpu, std::min(maximum.gpu, raw.gpu - shift));
    if (cpu + gpu > 2.0) {
      lo = shift;
    } else {
      hi = shift;
    }
  }
  const double shift = (lo + hi) / 2.0;
  WeightPair projected;
  projected.cpu = std::max(minimum.cpu, std::min(maximum.cpu, raw.cpu - shift));
  projected.gpu = std::max(minimum.gpu, std::min(maximum.gpu, raw.gpu - shift));
  return projected;
}

inline double l1_variation(const WeightPair& left, const WeightPair& right) {
  return std::abs(left.cpu - right.cpu) + std::abs(left.gpu - right.gpu);
}

inline UpdateSignal classify_update(double latency_ms, double deadline_ms, std::size_t gpu_queue_depth) {
  if (!std::isfinite(latency_ms) || !std::isfinite(deadline_ms) || latency_ms < 0.0 || deadline_ms <= 0.0) {
    throw std::runtime_error("Weighted proxy update contains an invalid latency or deadline");
  }
  if (latency_ms > deadline_ms && gpu_queue_depth > 0) {
    return UpdateSignal::PenalizeGpu;
  }
  if (latency_ms <= deadline_ms && gpu_queue_depth == 0) {
    return UpdateSignal::RewardGpu;
  }
  return UpdateSignal::None;
}

inline double update_delta(UpdateSignal signal, double penalty_step = 0.002, double reward_step = 0.0002) {
  if (!std::isfinite(penalty_step) || !std::isfinite(reward_step) || penalty_step <= 0.0 || reward_step <= 0.0) {
    throw std::runtime_error("Weighted proxy update steps must be finite and positive");
  }
  if (signal == UpdateSignal::PenalizeGpu) {
    return penalty_step;
  }
  if (signal == UpdateSignal::RewardGpu) {
    return -reward_step;
  }
  return 0.0;
}

inline double apply_weight_delta(double old_weight,
                                 double delta,
                                 double minimum_weight = 0.5,
                                 double maximum_weight = 1.5) {
  if (!std::isfinite(old_weight) || !std::isfinite(delta) || !std::isfinite(minimum_weight) ||
      !std::isfinite(maximum_weight) || minimum_weight <= 0.0 || maximum_weight < minimum_weight) {
    throw std::runtime_error("Weighted proxy update bounds are invalid");
  }
  return std::max(minimum_weight, std::min(maximum_weight, old_weight + delta));
}

inline const char* update_reason(UpdateSignal signal) {
  if (signal == UpdateSignal::PenalizeGpu) {
    return "prototype_deadline_miss_with_gpu_backlog";
  }
  if (signal == UpdateSignal::RewardGpu) {
    return "prototype_on_time_with_empty_gpu_queue";
  }
  return "no_weight_update";
}

struct FeedbackGateInput {
  UpdateSignal signal = UpdateSignal::None;
  bool censored = false;
  std::uint64_t parameter_lag = 0;
  std::uint64_t lag_limit = 0;
  std::uint64_t events_since_update = 0;
  std::uint64_t cooldown_events = 0;
  double candidate_variation = 0.0;
  double variation_before = 0.0;
  double variation_budget = 0.0;
  bool has_first_consumer = true;
};

struct FeedbackGateDecision {
  bool apply = false;
  std::string reason;
};

inline FeedbackGateDecision evaluate_feedback_gate(const FeedbackGateInput& input) {
  if (!std::isfinite(input.candidate_variation) || !std::isfinite(input.variation_before) ||
      !std::isfinite(input.variation_budget) || input.candidate_variation < 0.0 ||
      input.variation_before < 0.0 || input.variation_budget < 0.0) {
    throw std::runtime_error("Weighted proxy feedback variation is invalid");
  }
  if (input.censored) {
    return {false, "censored_feedback"};
  }
  if (input.parameter_lag > input.lag_limit) {
    return {false, "stale_feedback"};
  }
  if (input.events_since_update < input.cooldown_events) {
    return {false, "cooldown_active"};
  }
  if (input.signal == UpdateSignal::None || input.candidate_variation <= 1e-12) {
    return {false, "no_weight_update"};
  }
  if (input.variation_before + input.candidate_variation > input.variation_budget + 1e-12) {
    return {false, "variation_budget_exhausted"};
  }
  if (!input.has_first_consumer) {
    return {false, "no_subsequent_decision_before_end"};
  }
  return {true, update_reason(input.signal)};
}

}  // namespace vast_weighted_proxy
