"""Tests for backend/prediction/model.py -- Monte Carlo position prediction."""

from __future__ import annotations

import pytest

from backend.prediction.model import TimeDistribution, predict_position


def test_no_opponents_is_honestly_insufficient_data():
    own = TimeDistribution("44", mean_s=5000.0, std_s=10.0)
    prediction = predict_position(own, [], current_position=5, lap=20)

    assert prediction.source == "insufficient_opponent_data"
    assert prediction.position_probabilities == {}
    assert prediction.expected_position is None


def test_dominant_car_wins_p1_with_high_probability():
    own = TimeDistribution("44", mean_s=4500.0, std_s=5.0)  # much faster (lower time)
    opponents = [
        TimeDistribution("1", mean_s=4700.0, std_s=5.0),
        TimeDistribution("16", mean_s=4750.0, std_s=5.0),
    ]

    prediction = predict_position(own, opponents, current_position=3, lap=20)

    assert prediction.source == "monte_carlo"
    assert prediction.position_probabilities.get(1, 0.0) > 0.95
    assert prediction.expected_position == pytest.approx(1.0, abs=0.1)


def test_slow_car_finishes_last_with_high_probability():
    own = TimeDistribution("44", mean_s=5200.0, std_s=5.0)  # much slower
    opponents = [
        TimeDistribution("1", mean_s=4700.0, std_s=5.0),
        TimeDistribution("16", mean_s=4750.0, std_s=5.0),
    ]

    prediction = predict_position(own, opponents, current_position=1, lap=20)

    assert prediction.position_probabilities.get(3, 0.0) > 0.95
    assert prediction.risk_of_losing_positions > 0.95  # started P1, will lose positions


def test_probabilities_sum_to_one():
    own = TimeDistribution("44", mean_s=4900.0, std_s=15.0)
    opponents = [TimeDistribution("1", mean_s=4880.0, std_s=15.0), TimeDistribution("16", mean_s=4920.0, std_s=15.0)]

    prediction = predict_position(own, opponents, current_position=2, lap=20)

    assert sum(prediction.position_probabilities.values()) == pytest.approx(1.0, abs=1e-9)


def test_close_field_spreads_probability_across_multiple_positions():
    own = TimeDistribution("44", mean_s=4900.0, std_s=20.0)
    opponents = [
        TimeDistribution("1", mean_s=4895.0, std_s=20.0),
        TimeDistribution("16", mean_s=4905.0, std_s=20.0),
    ]

    prediction = predict_position(own, opponents, current_position=2, lap=20)

    nonzero_positions = [p for p, prob in prediction.position_probabilities.items() if prob > 0.01]
    assert len(nonzero_positions) >= 2


def test_deterministic_given_same_seed():
    own = TimeDistribution("44", mean_s=4900.0, std_s=20.0)
    opponents = [TimeDistribution("1", mean_s=4895.0, std_s=20.0)]

    a = predict_position(own, opponents, current_position=2, lap=20, seed=7)
    b = predict_position(own, opponents, current_position=2, lap=20, seed=7)

    assert a.position_probabilities == b.position_probabilities
    assert a.expected_position == b.expected_position


def test_expected_position_matches_probability_weighted_average():
    own = TimeDistribution("44", mean_s=4900.0, std_s=20.0)
    opponents = [TimeDistribution("1", mean_s=4895.0, std_s=20.0), TimeDistribution("16", mean_s=4910.0, std_s=20.0)]

    prediction = predict_position(own, opponents, current_position=2, lap=20)

    manual = sum(pos * prob for pos, prob in prediction.position_probabilities.items())
    assert prediction.expected_position == pytest.approx(manual, abs=0.05)
