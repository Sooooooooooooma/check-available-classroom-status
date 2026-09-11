import type { Classroom } from "../types"

type Props = {
  classroom: Classroom;
};

function ClassroomCard({classroom}:Props) {
  return (
    <div>{classroom.name}</div>
  )
}

export default ClassroomCard
