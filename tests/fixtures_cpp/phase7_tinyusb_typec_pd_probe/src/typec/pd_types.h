#pragma once
#include "common/tusb_common.h"
enum { PD_REV_30 = 2 };
enum { PD_DATA_ROLE_UFP = 0, PD_DATA_ROLE_DFP = 1 };
enum { PD_POWER_ROLE_SINK = 0, PD_POWER_ROLE_SOURCE = 1 };
enum { PD_DATA_SOURCE_CAP = 1, PD_DATA_REQUEST = 2 };
enum { PD_CTRL_ACCEPT = 3, PD_CTRL_REJECT = 4, PD_CTRL_PS_READY = 6 };
enum { PD_PDO_TYPE_FIXED = 0, PD_PDO_TYPE_BATTERY = 1, PD_PDO_TYPE_VARIABLE = 2, PD_PDO_TYPE_APDO = 3 };
typedef struct TU_ATTR_PACKED { unsigned msg_type:5; unsigned data_role:1; unsigned specs_rev:2; unsigned power_role:1; unsigned msg_id:3; unsigned n_data_obj:3; unsigned extended:1; } pd_header_t;
typedef struct TU_ATTR_PACKED { unsigned current_max_10ma:10; unsigned voltage_50mv:10; unsigned type:2; } pd_pdo_fixed_t;
typedef struct TU_ATTR_PACKED { unsigned current_extremum_10ma:10; unsigned current_operate_10ma:10; unsigned reserved:3; unsigned epr_mode_capable:1; unsigned unchunked_ext_msg_support:1; unsigned no_usb_suspend:1; unsigned usb_comm_capable:1; unsigned capability_mismatch:1; unsigned give_back_flag:1; unsigned object_position:3; } pd_rdo_fixed_variable_t;
