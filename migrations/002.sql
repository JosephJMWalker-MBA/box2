ALTER TABLE bookings ADD COLUMN duration_minutes INTEGER NOT NULL DEFAULT 5 CHECK(duration_minutes IN (5,10,15));
ALTER TABLE bookings ADD COLUMN block_count INTEGER NOT NULL DEFAULT 1 CHECK(block_count IN (1,2,3) AND duration_minutes=block_count*5);
CREATE TABLE booking_allocations (
 booking_id TEXT NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
 slot_id INTEGER NOT NULL REFERENCES slots(id),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 PRIMARY KEY(booking_id,slot_id)
);
CREATE UNIQUE INDEX active_allocation ON booking_allocations(slot_id) WHERE active=1;
INSERT INTO booking_allocations(booking_id,slot_id,active)
 SELECT id,slot_id,CASE WHEN status='cancelled' THEN 0 ELSE 1 END FROM bookings;
CREATE TRIGGER release_cancelled_allocations AFTER UPDATE OF status ON bookings
 WHEN NEW.status='cancelled'
 BEGIN
  UPDATE booking_allocations SET active=0 WHERE booking_id=NEW.id;
 END;
