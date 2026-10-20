import json
import math
import unittest
from datetime import date
import test_candidate_engine
from candidate_engine import fit_rating_model,calibrated_prediction,calibrate_ratings
from kp_sync import rated_airing_series

class UpdateTests(unittest.TestCase):
    def test_calibration_uses_owner_scale_and_spreads_supported_predictions(self):
        points=[(i/100, 4+i/10) for i in range(10,51)]
        model=fit_rating_model(points)
        self.assertGreater(calibrated_prediction(100*math.exp(.5),model),8)
        self.assertLess(calibrated_prediction(100*math.exp(.1),model),6)
        self.assertAlmostEqual(calibrated_prediction(100*math.exp(model['mean_x']),model),model['mean_rating'])
        constant=fit_rating_model([(0,7)]*30)
        self.assertEqual(calibrated_prediction(150,constant),7)

    def test_owner_contribution_removed_from_affinity(self):
        c=test_candidate_engine.CandidateEngineTests().connection()
        c.execute("INSERT INTO media(kp_id,title,media_type,kp_rating,metadata_status) VALUES(1,'A','movie',7,'ready')")
        c.execute("INSERT INTO user_ratings(profile_id,kp_id,rating) VALUES('owner',1,8)")
        c.execute("INSERT INTO rating_scale VALUES('owner',8,'eight',.7)")
        c.execute("INSERT INTO features(feature_id,feature_type,name) VALUES(1,'genre','sf')")
        c.execute("INSERT INTO media_features VALUES(1,1,1,'test')")
        c.execute("INSERT INTO profile_feature_stats VALUES('owner',1,1,1,8,.7,1,0,1,.1,1.5,1,1)")
        model=calibrate_ratings(c,'owner')
        self.assertAlmostEqual(model['mean_x'],math.log(1.1)) # quality only; own genre signal removed
        self.assertEqual(model['mean_rating'],8)
        c.close()

    def test_airing_requires_owner_rating_and_recent_dates(self):
        c=test_candidate_engine.CandidateEngineTests().connection()
        for i in range(1,6):
            c.execute("INSERT INTO media(kp_id,title,media_type) VALUES(?,'Dark matter','tv')",(i,))
            if i!=5:c.execute("INSERT INTO user_ratings(profile_id,kp_id,rating) VALUES('owner',?,8)",(i,))
            c.execute("""INSERT INTO series_tracking(profile_id,kp_id,tracking_mode,airing_state,next_air_date,last_air_date,state_reason,updated_at)
                       VALUES('owner',?,?,'airing',?,?,'test',1)""",(i,'muted' if i==4 else 'auto',
                       '2026-10-02' if i!=2 else '2027-10-02','2026-09-29' if i==3 else None))
        c.execute("UPDATE series_tracking SET active_from='2026-09-01' WHERE kp_id IN (1,3,4,5)")
        rows=rated_airing_series(c,'owner',date(2026,9,30))
        self.assertEqual({r['kp_id'] for r in rows},{1,3})
        self.assertTrue(all(r['my_rating']==8 for r in rows))
        self.assertNotIn('time',rows[0])
        c.close()

if __name__=='__main__':unittest.main()
