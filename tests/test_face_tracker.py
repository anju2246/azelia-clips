import pytest
import numpy as np
from packages.clips.vision.face_tracker import FaceDetection, IdentityStore

def test_face_detection_properties():
    # Test valid width/height
    det = FaceDetection(
        frame_idx=0, 
        timestamp=0.0, 
        x=100, 
        y=200, 
        width=50, 
        height=80
    )
    
    assert det.center_x == 125
    assert det.center_y == 240
    
    # Negative dimensions (graceful fallback expected if possible, or just exact math)
    det2 = FaceDetection(
        frame_idx=0, 
        timestamp=0.0, 
        x=50, 
        y=50, 
        width=-10, 
        height=-10
    )
    assert det2.center_x == 45
    assert det2.center_y == 45


def test_identity_store_matching():
    store = IdentityStore(similarity_threshold=0.6)
    
    # 1. Add first face
    emb1 = np.array([1.0, 0.0, 0.0]) # Norm is 1
    fid1 = store.match_or_create(emb1)
    
    assert fid1.face_id == "FACE_00"
    assert any(i.face_id == "FACE_00" for i in store.identities)
    assert next(i for i in store.identities if i.face_id == "FACE_00").count == 1
    
    # 2. Add very similar face (cosine sim = 0.99)
    emb2 = np.array([0.9, 0.1, 0.0])
    emb2 = emb2 / np.linalg.norm(emb2)
    fid2 = store.match_or_create(emb2)
    
    assert fid2.face_id == "FACE_00" # Should match
    assert next(i for i in store.identities if i.face_id == "FACE_00").count == 2
    
    # 3. Add completely different face (cosine sim = 0.0)
    emb3 = np.array([0.0, 1.0, 0.0])
    fid3 = store.match_or_create(emb3)
    
    assert fid3.face_id == "FACE_01" # Should create new
    assert next(i for i in store.identities if i.face_id == "FACE_01").count == 1
    assert any(i.face_id == "FACE_01" for i in store.identities)
    
    # Ensure prototype updated correctly
    proto00 = next(i for i in store.identities if i.face_id == "FACE_00").embedding
    # It should be average of emb1 and emb2, then normalized
    expected_avg = (emb1 + emb2) / 2
    expected_proto = expected_avg / np.linalg.norm(expected_avg)
    np.testing.assert_array_almost_equal(proto00, expected_proto)

def test_identity_store_no_match_due_to_threshold():
    store = IdentityStore(similarity_threshold=0.99) # Very strict
    
    emb1 = np.array([1.0, 0.0, 0.0])
    store.match_or_create(emb1)
    
    # Even a slight difference should trigger a new identity
    emb2 = np.array([0.95, 0.312, 0.0])
    emb2 = emb2 / np.linalg.norm(emb2)
    
    fid2 = store.match_or_create(emb2)
    assert fid2.face_id == "FACE_01"
