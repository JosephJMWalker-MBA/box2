<?php
declare(strict_types=1);
// Synthetic assertions only; never call this helper from application/operator code.
function synthetic_off_checks(): array
{
    return array_fill_keys(array_keys(ROOM_OFF_CHECKS),1)+['channel_stopped'=>1];
}
function synthetic_house_checks(): array
{
    return synthetic_off_checks()+array_fill_keys(array_keys(HOUSE_CHECKS),1)+['viewer_reference'=>'Synthetic outside-viewer reference; no real hardware verification'];
}
function synthetic_stage_checks(): array
{
    return array_fill_keys(array_keys(STAGE_CHECKS),1);
}
