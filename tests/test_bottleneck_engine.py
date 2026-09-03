from app.bottleneck.engine import compute_bottlenecks


def test_no_edges_returns_no_risks(edge_factory):
    assert compute_bottlenecks([]) == []


def test_root_service_has_zero_fan_in(edge_factory):
    edges = [edge_factory("gateway", "checkout"), edge_factory("checkout", "redis")]
    risks = compute_bottlenecks(edges)
    gateway = next(r for r in risks if r.service == "gateway")
    assert gateway.fan_in == 0


def test_shared_dependency_has_higher_fan_in_than_a_single_caller_dependency(edge_factory):
    edges = [
        edge_factory("checkout", "redis"),
        edge_factory("payments", "redis"),
        edge_factory("inventory", "postgres"),
    ]
    risks = {r.service: r for r in compute_bottlenecks(edges)}
    assert risks["redis"].fan_in == 2
    assert risks["postgres"].fan_in == 1


def test_shared_errorprone_dependency_outranks_a_purely_central_node(edge_factory):
    """
    The exact scenario verified live: a gateway sits on every critical
    path (highest possible critical-path membership) but has zero
    fan-in and zero errors, while a shared, error-prone dependency has
    real fan-in and a real error rate. The shared dependency should
    still come out on top -- risk isn't just "how central are you,"
    it's fan-in + critical-path + error rate together.
    """
    edges = [
        edge_factory("gateway", "checkout", current_error_rate=0.0),
        edge_factory("gateway", "payments", current_error_rate=0.0),
        edge_factory("checkout", "redis", current_error_rate=0.3),
        edge_factory("payments", "redis", current_error_rate=0.3),
    ]
    risks = {r.service: r for r in compute_bottlenecks(edges)}

    assert risks["redis"].risk_score > risks["gateway"].risk_score


def test_contributing_edges_lists_only_edges_touching_that_service(edge_factory):
    edges = [
        edge_factory("checkout", "redis"),
        edge_factory("payments", "redis"),
        edge_factory("inventory", "postgres"),
    ]
    risks = {r.service: r for r in compute_bottlenecks(edges)}
    assert set(risks["redis"].contributing_edges) == {"checkout->redis", "payments->redis"}
    assert "inventory->postgres" not in risks["redis"].contributing_edges


def test_risk_scores_are_bounded_between_zero_and_one(edge_factory):
    edges = [
        edge_factory("a", "b", current_error_rate=1.0),
        edge_factory("c", "b", current_error_rate=1.0),
        edge_factory("d", "b", current_error_rate=1.0),
    ]
    for r in compute_bottlenecks(edges):
        assert 0.0 <= r.risk_score <= 1.0


def test_error_rate_alone_raises_risk_score_holding_topology_fixed(edge_factory):
    """
    Isolates error rate's contribution specifically -- same topology
    (so fan_in and critical-path membership are identical) in both
    graphs, only the error rate differs. If error rate stopped
    contributing to the formula, this would fail even though a test
    that also varies fan_in alongside error rate (see above) might
    not notice, since fan_in alone can be enough to differentiate two
    nodes in some topologies.
    """
    healthy = [
        edge_factory("checkout", "redis", current_error_rate=0.0),
        edge_factory("payments", "redis", current_error_rate=0.0),
    ]
    erroring = [
        edge_factory("checkout", "redis", current_error_rate=0.5),
        edge_factory("payments", "redis", current_error_rate=0.5),
    ]
    healthy_risk = next(r for r in compute_bottlenecks(healthy) if r.service == "redis")
    erroring_risk = next(r for r in compute_bottlenecks(erroring) if r.service == "redis")

    assert erroring_risk.risk_score > healthy_risk.risk_score