<?php $arrival = arrival_times($booking['start_at_utc']); ?>
<dl><dt>Booking code</dt><dd><?= e($booking['id']) ?></dd>
<dt>Show evening</dt><dd><?= e($booking['show_date']) ?></dd>
<dt>Stage date/time block</dt><dd><?= e(time_range($booking['start_at_utc'], $booking['stage_end_at_utc'])) ?></dd>
<dt>Set length</dt><dd><?= (int)$booking['duration_minutes'] ?> stage minutes</dd>
<dt>Calendar reservation</dt><dd><?= (int)$booking['block_count'] * 10 ?> minutes · <?= (int)$booking['block_count'] ?> adjacent allocations, including host/reset buffer<br><?= e(time_range($booking['start_at_utc'], $booking['reservation_end_at_utc'])) ?></dd>
<dt>Arrival window</dt><dd><?= e(arrival_window($booking['start_at_utc'])) ?><br>Check in immediately upon arrival. Do not arrive before T−20.</dd>
<dt>On deck at</dt><dd><?= e(local_label($arrival['on_deck_at_utc'])) ?></dd></dl>
