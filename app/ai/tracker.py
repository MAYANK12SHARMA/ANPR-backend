"""
Vehicle Tracker Integration for ANPR System
Filters detections to only those crossing the line within ROI
"""

import numpy as np
from scipy.optimize import linear_sum_assignment
from collections import defaultdict


class VehicleTracker:
    """Multi-object tracker with global ID system"""
    
    def __init__(self, max_disappeared=30, max_distance=80):
        self.next_id = 0
        self.tracks = {}
        self.max_disappeared = max_disappeared
        self.max_distance = max_distance
    
    def update(self, detections):
        """
        Update tracker with new detections
        
        Args:
            detections: List of [x1, y1, x2, y2, conf, class_id]
        
        Returns:
            List of [x1, y1, x2, y2, track_id, class_id]
        """
        if len(detections) == 0:
            self._handle_disappeared()
            return []
        
        bboxes = np.array([[d[0], d[1], d[2], d[3]] for d in detections])
        classes = np.array([d[5] if len(d) > 5 else 0 for d in detections])
        centroids = self._compute_centroids(bboxes)
        
        if len(self.tracks) == 0:
            return self._initialize_tracks(bboxes, centroids, classes)
        
        track_ids = list(self.tracks.keys())
        track_centroids = np.array([self.tracks[tid].centroid for tid in track_ids])
        
        cost_matrix = self._compute_cost_matrix(track_centroids, centroids)
        
        matched_tracks, matched_detections, unmatched_tracks, unmatched_detections = \
            self._match_detections_to_tracks(cost_matrix, track_ids)
        
        for track_idx, det_idx in zip(matched_tracks, matched_detections):
            track_id = track_ids[track_idx]
            self.tracks[track_id].update(
                bbox=bboxes[det_idx],
                centroid=centroids[det_idx],
                class_id=classes[det_idx]
            )
        
        for track_idx in unmatched_tracks:
            track_id = track_ids[track_idx]
            self.tracks[track_id].disappeared += 1
            if self.tracks[track_id].disappeared > self.max_disappeared:
                del self.tracks[track_id]
        
        for det_idx in unmatched_detections:
            track_id = self.next_id
            self.tracks[track_id] = TrackState(
                track_id=track_id,
                bbox=bboxes[det_idx],
                centroid=centroids[det_idx],
                class_id=classes[det_idx]
            )
            self.next_id += 1
        
        outputs = []
        for track_id, track in self.tracks.items():
            if track.disappeared == 0:
                x1, y1, x2, y2 = track.bbox
                outputs.append([x1, y1, x2, y2, track_id, track.class_id])
        
        return outputs
    
    def _compute_centroids(self, bboxes):
        centroids = np.zeros((len(bboxes), 2), dtype=np.float32)
        for i, bbox in enumerate(bboxes):
            centroids[i] = [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2]
        return centroids
    
    def _compute_cost_matrix(self, track_centroids, detection_centroids):
        cost_matrix = np.linalg.norm(
            track_centroids[:, np.newaxis] - detection_centroids[np.newaxis, :],
            axis=2
        )
        return cost_matrix
    
    def _match_detections_to_tracks(self, cost_matrix, track_ids):
        cost_matrix_thresh = cost_matrix.copy()
        cost_matrix_thresh[cost_matrix_thresh > self.max_distance] = 1e6
        
        row_indices, col_indices = linear_sum_assignment(cost_matrix_thresh)
        
        matched_tracks = []
        matched_detections = []
        
        for row, col in zip(row_indices, col_indices):
            if cost_matrix[row, col] < self.max_distance:
                matched_tracks.append(row)
                matched_detections.append(col)
        
        all_track_indices = set(range(cost_matrix.shape[0]))
        all_det_indices = set(range(cost_matrix.shape[1]))
        
        unmatched_tracks = list(all_track_indices - set(matched_tracks))
        unmatched_detections = list(all_det_indices - set(matched_detections))
        
        return matched_tracks, matched_detections, unmatched_tracks, unmatched_detections
    
    def _initialize_tracks(self, bboxes, centroids, classes):
        outputs = []
        for bbox, centroid, class_id in zip(bboxes, centroids, classes):
            track_id = self.next_id
            self.tracks[track_id] = TrackState(
                track_id=track_id,
                bbox=bbox,
                centroid=centroid,
                class_id=class_id
            )
            self.next_id += 1
            
            x1, y1, x2, y2 = bbox
            outputs.append([x1, y1, x2, y2, track_id, class_id])
        
        return outputs
    
    def _handle_disappeared(self):
        for track_id in list(self.tracks.keys()):
            self.tracks[track_id].disappeared += 1
            if self.tracks[track_id].disappeared > self.max_disappeared:
                del self.tracks[track_id]
    
    def get_previous_centroid(self, track_id):
        if track_id in self.tracks and len(self.tracks[track_id].history) >= 2:
            return self.tracks[track_id].history[-2]
        return None


class TrackState:
    """State of a tracked object"""
    
    def __init__(self, track_id, bbox, centroid, class_id):
        self.track_id = track_id
        self.bbox = bbox
        self.centroid = centroid
        self.class_id = class_id
        self.disappeared = 0
        self.history = [centroid]
        self.max_history = 30
    
    def update(self, bbox, centroid, class_id):
        self.bbox = bbox
        self.centroid = centroid
        self.class_id = class_id
        self.disappeared = 0
        self.history.append(centroid)
        if len(self.history) > self.max_history:
            self.history.pop(0)


class LineCrossCounter:
    """Line crossing detection"""
    
    def __init__(self, line_point1, line_point2):
        self.p1 = np.array(line_point1, dtype=np.float32)
        self.p2 = np.array(line_point2, dtype=np.float32)
        self.line_vec = self.p2 - self.p1
        self.counted_ids = set()
        self.previous_sides = {}
    
    def check_crossing(self, track_id, current_centroid, previous_centroid=None):
        """Check if track crossed the line"""
        if track_id in self.counted_ids:
            return False
        
        current_side = self._compute_side(current_centroid)
        
        if previous_centroid is not None:
            previous_side = self._compute_side(previous_centroid)
        elif track_id in self.previous_sides:
            previous_side = self.previous_sides[track_id]
        else:
            self.previous_sides[track_id] = current_side
            return False
        
        if previous_side != current_side and previous_side != 0 and current_side != 0:
            distance = self._point_to_line_distance(current_centroid)
            if distance < 50:
                self.counted_ids.add(track_id)
                return True
        
        self.previous_sides[track_id] = current_side
        return False
    
    def _compute_side(self, point):
        point = np.array(point, dtype=np.float32)
        cross = np.cross(self.line_vec, point - self.p1)
        
        if cross > 5:
            return 1
        elif cross < -5:
            return -1
        else:
            return 0
    
    def _point_to_line_distance(self, point):
        point = np.array(point, dtype=np.float32)
        v = point - self.p1
        line_length = np.linalg.norm(self.line_vec)
        if line_length == 0:
            return np.linalg.norm(v)
        cross_product = np.abs(np.cross(self.line_vec, v))
        distance = cross_product / line_length
        return distance
