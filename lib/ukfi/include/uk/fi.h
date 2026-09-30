#ifndef __UK_FI_H__
	#define __UK_FI_H__

	#include <uk/essentials.h>
	#include <uk/config.h>
	#include <uk/print.h>

	#define UK_FI_DISARMED 0
	#define UK_FI_ARMED 1

	#define CAN_FAIL 1
	#define CANNOT_FAIL 0


	enum uk_fi_faults {
		UK_FI_FAULT_NONE = 0,
		UK_FI_FAULT_CRASH,
		UK_FI_FAULT_HANG,
		UK_FI_FAULT_ERROR,
		#if CONFIG_LIBUKSCHED
			UK_FI_FAULT_DELAY,
		#endif
		UK_FI_FAULT_MAX
	};

	struct uk_fi_triggers {
		unsigned n_invocations;
		unsigned period;
		unsigned prob_on_100000;
	};

	struct uk_fi_site {
		const char *libname;
		const char *site;
		unsigned long inv;
		int armed;
		struct uk_fi_triggers trigger;
		enum uk_fi_faults faulttype;
		const char *file;
		int line;
		int can_fail;
	};

	extern struct uk_fi_site uk_fitab_start[];
    extern struct uk_fi_site uk_fitab_end;


	#if CONFIG_LIBUKFI

	#define _UK_FI_CONCAT(a,b) a##b
	#define UK_FI_CONCAT(a,b) _UK_FI_CONCAT(a,b)

	#define uk_fi_foreach(itr, fitab_start, fitab_end)		\
		for ((itr) = (fitab_start);	\
			(itr) < &(fitab_end);					\
			(itr)++)



	#define UK_FI_COUNT(s)   ((s).inv++)

	int uk_fi_hit(struct uk_fi_site *site);

	#define __UK_FI_DECL(name, var, cf)	\
		static struct uk_fi_site __used __section(".uk_fitab") __align(8) var={	\
			.libname = STRINGIFY(__LIBNAME__),	\
			.site = name,	\
			.can_fail = cf, \
			.file = __FILE__,	\
			.line = __LINE__	\
		}


	//if two sites are on the same block, they will have the same name, so we need to use __LINE__ to make them unique
	//regardless, two sites on the same line will collide.
	#define UK_FI_SITE(name)    \
		do{    \
			__UK_FI_DECL(name, UK_FI_CONCAT(__uk_fi_, __LINE__), CANNOT_FAIL);	\
			UK_FI_COUNT(UK_FI_CONCAT(__uk_fi_, __LINE__));	\
			if(unlikely(UK_FI_CONCAT(__uk_fi_, __LINE__).armed) ) {	\
				int ret = uk_fi_hit(&UK_FI_CONCAT(__uk_fi_, __LINE__)); 	\
				if(ret) {	\
					uk_pr_warn("Fault injection site %s:%d wants to return an error but can't\n", __FILE__, __LINE__);	\
				}	\
			}	\
		}while(0);	

	#define UK_FI_SITE_ERR(name, err)    \
		do{    \
			__UK_FI_DECL(name, UK_FI_CONCAT(__uk_fi_, __LINE__), CAN_FAIL);	\
			UK_FI_COUNT(UK_FI_CONCAT(__uk_fi_, __LINE__));	\
			if(unlikely(UK_FI_CONCAT(__uk_fi_, __LINE__).armed)) {	\
				int __returned = uk_fi_hit(&UK_FI_CONCAT(__uk_fi_, __LINE__)); \
				if(__returned) \
					return (err);	\
			}   \
		}while(0);	
		
	#else
	#define UK_FI_SITE(name) do{}while(0)
	#define UK_FI_SITE_ERR(name, err) do{}while(0)
	#endif


#endif