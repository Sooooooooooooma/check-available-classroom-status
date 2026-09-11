import ClassroomCard from "./ClassroomCard"
import type { Classroom } from "../types"

type Props = {
    classrooms: Classroom[];
};

function ClassroomList({classrooms}: Props ) {
    return (
        <div>
            {classrooms.map((classroom) => (
                <ClassroomCard
                    key={classroom.id}
                    classroom={classroom}
                />
            ))}
        </div>
    )
}

export default ClassroomList
