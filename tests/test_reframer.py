import pytest
from packages.clips.vision.reframer import VideoReframer

def test_simplify_trajectory():
    reframer = VideoReframer()
    
    # 1. A stationary trajectory should reduce to 2 points (start and end)
    traj1 = [(0.0, 100, 200), (0.5, 100, 200), (1.0, 100, 200)]
    simplified1 = reframer._simplify_trajectory(traj1)
    assert len(simplified1) == 2
    assert simplified1[0] == (0.0, 100, 200)
    assert simplified1[-1] == (1.0, 100, 200)
    
    # 2. A moving trajectory
    traj2 = [
        (0.0, 100, 200),
        (0.5, 100, 200), # stationary
        (1.0, 500, 500), # big jump!
        (1.5, 500, 500), # stationary again
        (2.0, 500, 500)
    ]
    simplified2 = reframer._simplify_trajectory(traj2)
    # Expected: (0.0, 100, 200), (0.5, 100, 200), (1.0, 500, 500), (2.0, 500, 500)
    # The actual implementation of simplify checks for diff > 50 in X or Y
    assert len(simplified2) > 2
    assert (1.0, 500, 500) in simplified2

def test_build_crop_expr():
    reframer = VideoReframer()
    
    # Simple 2-point keyframe set
    keypoints = [(0.0, 100), (5.0, 500)]
    expr = reframer._build_crop_expr(keypoints, half_crop=50, src_dim=1080, transition_secs=0.5)
    
    # It should clamp bounds. max_origin = 1080 - 100 = 980
    # origin1 = max(0, min(100 - 50, 980)) = 50
    # origin2 = max(0, min(500 - 50, 980)) = 450
    
    assert "50" in expr
    assert "450" in expr
    assert "if(" in expr
    assert "t" in expr
